"""Record the model once, then replay the whole suite offline.

    $env:TOKEN="..."; $env:CONN="..."; python evals/recorded.py --record --only 0-9
    $env:TOKEN="..."; $env:CONN="..."; python evals/recorded.py --replay

The free tier allows 20 requests per day per model and one case costs two or more, so a
30-question gate cannot be recorded in one sitting. `--only` records a slice and re-running
keeps what was already captured.

The suite runs many questions in a row against one tenant, so it trips the per-tenant rate
limit. Raise it for an eval run:

    $env:MAX_RUNS_PER_MINUTE="100"

Replay drives the real routes through TestClient rather than a socket, so it still exercises
auth, prepare_run, the App DB, the agent loop, the tool, the guard, the customer database and
the SSE encoding. `run_evals.py` remains the live gate over real HTTP.
"""

import argparse
import hashlib
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

sys.path.insert(0, str(Path(__file__).parent))

from run_evals import PASS_THRESHOLD, _matches

CASSETTE_DIR = Path(__file__).parent / "cassettes"


def _request_sha(messages: list[BaseMessage]) -> str:
    """Fingerprint what the model was asked, so a replay that no longer matches can say so.

    Message ids and response metadata vary between runs and are excluded. Tool-call ids are
    kept, because replay re-emits the recorded message verbatim, so they are stable.
    """
    shape = [
        [
            m.type,
            m.text,
            [[c["name"], c["args"]] for c in getattr(m, "tool_calls", [])],
            getattr(m, "tool_call_id", None),
        ]
        for m in messages
    ]
    return hashlib.sha256(json.dumps(shape, sort_keys=True, default=str).encode()).hexdigest()


def _tools_sha(tools: list[Any]) -> str:
    """Tool descriptions embed the customer's schema and never appear in the message list, so a
    schema change would otherwise slip past the per-turn fingerprint."""
    shape = sorted((getattr(t, "name", str(t)), getattr(t, "description", "")) for t in tools)
    return hashlib.sha256(json.dumps(shape).encode()).hexdigest()


def prompt_sha() -> str:
    """Hash what the model is actually given for this suite, not the module's constants.

    Splitting the system prompt into capability blocks changed the constants without changing a
    byte the model sees, and re-recording costs a day of quota, so the hash must not move for a
    refactor.
    """
    from app.agent import prompts

    composed = prompts.AGENT_SYSTEM.format(today="{today}", capability=prompts.SQL_CAPABILITY)
    text = composed + prompts.QUERY_TOOL_DESC + prompts.QUERY_TOOL_SQL_ARG
    return hashlib.sha256(text.encode()).hexdigest()


def cassette_path(cases_path: Path) -> Path:
    """The prompt hash is in the name, so editing a prompt makes the cassette unfindable and
    replay fails loudly rather than scoring yesterday's behaviour against today's prompt."""
    return CASSETTE_DIR / f"{cases_path.stem}.{prompt_sha()[:8]}.json"


class RecordingChatModel(BaseChatModel):
    """Delegates to the real model and keeps every reply."""

    inner: Any
    turns: list = Field(default_factory=list)
    tools_sha: str = ""

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "RecordingChatModel":
        self.tools_sha = _tools_sha(tools)
        self.inner = self.inner.bind_tools(tools, **kwargs)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        message = self.inner.invoke(messages, stop=stop, **kwargs)
        self.turns.append({"request_sha": _request_sha(messages), "message": message.model_dump()})
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "recording"


class CassetteChatModel(BaseChatModel):
    """Replays one case's recorded replies in order, reporting any that no longer match."""

    turns: list
    tools_sha: str = ""
    index: int = 0
    drift: list = Field(default_factory=list)

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "CassetteChatModel":
        if self.tools_sha and _tools_sha(tools) != self.tools_sha:
            self.drift.append("tool descriptions")
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self.index >= len(self.turns):
            raise RuntimeError("the recording ran out of replies; re-record this case")
        turn = self.turns[self.index]
        if _request_sha(messages) != turn["request_sha"]:
            self.drift.append(f"turn {self.index}")
        self.index += 1
        message = AIMessage.model_validate(turn["message"])
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "cassette"


@contextmanager
def frozen_today(day: str):
    """The system prompt interpolates today's date, so replay must see the day it recorded.

    Normalising the fingerprint instead would leave a second bug in place: a question like
    "last month" would resolve against a different month than the one that produced the answer.
    """
    with patch("app.agent.graph.date", SimpleNamespace(today=lambda: date.fromisoformat(day))):
        yield


def _parse_sse(text: str) -> dict:
    result: dict[str, Any] = {"rows": [], "answer": "", "sql": None, "chart": None, "error": None}
    event = None
    for line in text.splitlines():
        if line.startswith("event:"):
            event = line.removeprefix("event:").strip()
        elif line.startswith("data:") and event:
            data = json.loads(line.removeprefix("data:").strip())
            if event == "rows":
                result["rows"] = data.get("rows", [])
            elif event == "token":
                result["answer"] += data.get("text", "")
            elif event == "sql":
                result["sql"] = data.get("sql")
            elif event == "chart":
                result["chart"] = data
            elif event == "error":
                result["error"] = data.get("message")
    return result


def _ask(client, token: str, conn: str, question: str, thread_id: str) -> str:
    r = client.post(
        "/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"connection_id": conn, "thread_id": thread_id, "question": question},
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.text


def _client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())


def _env() -> tuple[str, str]:
    try:
        return os.environ["TOKEN"], os.environ["CONN"]
    except KeyError as e:
        raise SystemExit(f"set {e.args[0]} in the environment") from e


def _slice(spec: str | None, total: int) -> range:
    if spec is None:
        return range(total)
    lo, _, hi = spec.partition("-")
    return range(int(lo), min(int(hi or lo) + 1, total))


def record(cases_path: Path, only: str | None) -> int:
    from app.config import get_settings
    from app.llm import get_llm

    token, conn = _env()
    cases = yaml.safe_load(cases_path.read_text(encoding="utf-8")) or []
    path = cassette_path(cases_path)

    book = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    kept: dict[str, Any] = {c["q"]: c for c in book.get("cases", [])}

    stamp = uuid.uuid4().hex[:8]
    client = _client()

    for i in _slice(only, len(cases)):
        question = cases[i]["q"]
        if question in kept:
            print(f"KEPT | {question}")
            continue
        model = RecordingChatModel(inner=get_llm())
        try:
            with patch("app.agent.graph.get_llm", return_value=model):
                _ask(client, token, conn, question, f"rec-{stamp}-{i}")
        except Exception as e:
            # Almost always the daily quota. Keep what was captured and stop.
            print(f"STOP | {question}\n       {e}")
            break
        kept[question] = {"q": question, "turns": model.turns}
        book["tools_sha"] = model.tools_sha
        print(f"REC  | {question} ({len(model.turns)} turns)")

    book.update(
        {
            "recorded_on": book.get("recorded_on", date.today().isoformat()),
            "model": get_settings().gemini_model,
            "prompt_sha": prompt_sha(),
            "cases": [kept[c["q"]] for c in cases if c["q"] in kept],
        }
    )
    CASSETTE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(book, indent=2), encoding="utf-8")
    print(f"\n{len(book['cases'])}/{len(cases)} recorded -> {path.name}")
    return 0


def replay(cases_path: Path, verbose: bool) -> int:
    token, conn = _env()
    cases = yaml.safe_load(cases_path.read_text(encoding="utf-8")) or []
    path = cassette_path(cases_path)
    if not path.exists():
        print(
            f"no cassette for the current prompts at {path.name}. A prompt changed, so the "
            "recording no longer describes this agent. Re-record it.",
            file=sys.stderr,
        )
        return 2

    book = json.loads(path.read_text(encoding="utf-8"))
    turns_for = {c["q"]: c["turns"] for c in book["cases"]}
    stamp = uuid.uuid4().hex[:8]
    client = _client()

    passed, drifted, missing = 0, [], []
    with frozen_today(book["recorded_on"]):
        for i, case in enumerate(cases):
            question = case["q"]
            if question not in turns_for:
                missing.append(question)
                print(f"GAP  | {question}")
                continue
            model = CassetteChatModel(
                turns=turns_for[question], tools_sha=book.get("tools_sha", "")
            )
            with patch("app.agent.graph.get_llm", return_value=model):
                result = _parse_sse(_ask(client, token, conn, question, f"rep-{stamp}-{i}"))
            ok = result["error"] is None and _matches(case, result)
            passed += ok
            if model.drift:
                drifted.append(question)
            print(f"{'PASS' if ok else 'FAIL'} | {question}{' | DRIFT' if model.drift else ''}")
            if not ok and verbose:
                print(f"       sql:   {result['sql']}")
                print(f"       rows:  {result['rows'][:3]}")
                print(f"       error: {result['error']}")

    if missing:
        print(f"\n{len(missing)} case(s) never recorded, so no pass rate is reported.")
        return 2
    if drifted:
        print(
            f"\n{len(drifted)} case(s) drifted: the agent no longer sends what was recorded, so "
            "this run cannot be scored. Re-record."
        )
        return 2

    rate = passed / len(cases)
    print(f"\n{passed}/{len(cases)} ({rate:.0%}) replayed from {path.name}")
    return 0 if rate >= PASS_THRESHOLD else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", action="store_true", help="call the real model and save it")
    mode.add_argument("--replay", action="store_true", help="run offline against the recording")
    parser.add_argument("--cases", default="golden_sql.yaml")
    parser.add_argument("--only", help="record a slice, e.g. 0-9, to fit the daily quota")
    parser.add_argument("-v", "--verbose", action="store_true", help="print SQL for failures")
    args = parser.parse_args()

    cases_path = Path(__file__).parent / args.cases
    return record(cases_path, args.only) if args.record else replay(cases_path, args.verbose)


if __name__ == "__main__":
    sys.exit(main())

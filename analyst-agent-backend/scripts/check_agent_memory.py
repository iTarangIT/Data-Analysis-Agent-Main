"""Prove the agent's memory and context layers against a running service.

    uvicorn app.database_mcp:app --port 8001
    uvicorn app.main:app --port 8000
    $env:TOKEN = python scripts/supabase_token.py you@example.com
    $env:CONN="..."; $env:MAX_RUNS_PER_MINUTE="100"
    python scripts/check_agent_memory.py

Needs MEMORY_BACKEND=postgres, which is the default. Questions go through the real SSE endpoint
and a real model, so this costs free-tier quota - roughly eight calls, plus one per turn of the
context check.

What this can and cannot do. Whether a remembered definition *changed* an answer is a judgement
about prose, so the script prints the answers and says which one to read; everything it asserts
by itself it asserts against the store, not against model output.
"""

import argparse
import json
import os
import sys
import uuid
from functools import lru_cache
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import memory
from app.agent.context import RunContext
from app.agent.store import open_store

BASE = os.environ.get("AGENT_URL", "http://localhost:8000")
STAGES = ["router", "sql_gen", "sql_guard", "db_exec", "answer"]
KNOWN_EVENTS = {"status", "sql", "rows", "chart", "token", "done", "error"}

passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    (passed if ok else failed).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")
    return ok


def ask(client: httpx.Client, token: str, conn: str, thread: str, question: str) -> dict:
    out = {"stages": [], "events": [], "answer": "", "sql": None, "run_id": None, "error": None}
    with client.stream(
        "POST",
        f"{BASE}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"connection_id": conn, "thread_id": thread, "question": question},
        timeout=180,
    ) as r:
        if r.status_code != 200:
            r.read()
            out["error"] = f"HTTP {r.status_code}: {r.text[:200]}"
            return out
        event = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
                out["events"].append(event)
            elif line.startswith("data:") and event:
                data = json.loads(line.removeprefix("data:").strip())
                if event == "status":
                    out["stages"].append(data["stage"])
                elif event == "token":
                    out["answer"] += data.get("text", "")
                elif event == "sql":
                    out["sql"] = data.get("sql")
                elif event == "done":
                    out["run_id"] = data.get("run_id")
                elif event == "error":
                    out["error"] = data.get("message")
    return out


@lru_cache
def tenant_of(token: str) -> str:
    """The tenant is the account's, not the token's, so ask the service."""
    r = httpx.get(f"{BASE}/auth/me", headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()["tenant_id"]


def context_for(token: str, conn: str, thread: str) -> RunContext:
    return RunContext(tenant_id=tenant_of(token), connection_id=conn, run_id="-", thread_id=thread)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--turns", type=int, default=6, help="follow-ups used for the context-growth check"
    )
    parser.add_argument("--skip-growth", action="store_true", help="skip the costly turn loop")
    args = parser.parse_args()

    token, conn = os.environ.get("TOKEN"), os.environ.get("CONN")
    if not token or not conn:
        print("set TOKEN and CONN in the environment")
        return 2

    stamp = uuid.uuid4().hex[:6]
    first, second = f"mem-{stamp}-a", f"mem-{stamp}-b"
    client = httpx.Client()

    print("\n1. the SSE contract is unchanged")
    run = ask(client, token, conn, first, "how many rows are in the largest table?")
    if run["error"]:
        print(f"  run failed: {run['error']}")
        return 1
    check("no unknown event name", set(run["events"]) <= KNOWN_EVENTS, str(set(run["events"])))
    check(
        "stages are a prefix of the frozen sequence",
        run["stages"] == STAGES[: len(run["stages"])],
        " -> ".join(run["stages"]),
    )
    print(f"  answer: {run['answer'][:160]}")

    print("\n2. a definition taught in one thread is written to the store")
    taught = ask(
        client,
        token,
        conn,
        first,
        "Remember this for later: 'active record' means a row whose status column is 'active'.",
    )
    if taught["error"]:
        print(f"  run failed: {taught['error']}")
    with open_store() as store:
        recalled = memory.recall(store, context_for(token, conn, first))
    check("the glossary is no longer empty", "active record" in recalled.lower(), recalled[:120])

    print("\n3. a NEW thread sees it - the proof it is not the checkpointer")
    fresh = ask(client, token, conn, second, "What does 'active record' mean here?")
    with open_store() as store:
        in_new_thread = memory.recall(store, context_for(token, conn, second))
    check("the same memory is offered to a new thread", "active record" in in_new_thread.lower())
    print(f"  answer on the new thread: {fresh['answer'][:200]}")
    print("  ^ read this: it should use the definition, and this thread has no shared history")

    print("\n4. another tenant sees none of it")
    with open_store() as store:
        other = memory.recall(store, RunContext(f"t_not_{stamp}", conn, "-", "-"))
    check("a different tenant recalls nothing", other == "", other[:80])

    print("\n5. a thread record keeps no customer rows")
    with open_store() as store:
        kept = store.get((tenant_of(token), memory.THREADS), first)
    if kept:
        check(
            "only question, sql, answer and a timestamp are stored",
            set(kept.value) == {"question", "sql", "answer", "at"},
            str(sorted(kept.value)),
        )
    else:
        check("a thread record was written", False, "nothing stored for this thread")

    print("\n6. a query that answered is offered back as a worked example")
    with open_store() as store:
        again = memory.recall(store, context_for(token, conn, first))
    check("a remembered query is present", "select" in again.lower())

    if not args.skip_growth:
        print(f"\n7. context stops growing linearly ({args.turns} turns on one thread)")
        # The history list carries no token counts - it is a navigation surface - so each run is
        # fetched by id.
        run_ids = [run["run_id"], taught["run_id"]]
        for i in range(args.turns):
            turn = ask(client, token, conn, first, f"And the {i + 2}nd largest table?")
            run_ids.append(turn["run_id"])

        print("  prompt_tokens per turn on this thread:")
        counts = []
        for i, run_id in enumerate([r for r in run_ids if r], 1):
            row = client.get(
                f"{BASE}/runs/{run_id}", headers={"Authorization": f"Bearer {token}"}
            ).json()
            counts.append(row.get("prompt_tokens", 0))
            print(f"    turn {i:2}: {row.get('prompt_tokens')}")

        if len(counts) >= 4:
            early, late = counts[1] - counts[0], counts[-1] - counts[-2]
            check(
                "growth per turn is not still climbing at the end",
                late <= max(early, 1) * 2,
                f"first step +{early}, last step +{late}",
            )
        print("  ^ read this: it should flatten or drop, not climb straight")

    print(f"\n{len(passed)} passed, {len(failed)} failed")
    for name in failed:
        print(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

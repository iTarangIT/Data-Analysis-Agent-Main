"""Golden-question harness. Phase 1 is done at >= 80% (25 of 30).

    $env:TOKEN="..."; $env:CONN="..."; python evals/run_evals.py

The suite runs many questions in a row against one tenant, so it trips the per-tenant rate
limit. Raise it for an eval run:

    $env:MAX_RUNS_PER_MINUTE="100"

Runs every case through the real SSE endpoint, so it exercises the router,
the generator, the guard, execution and the answer together.
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

BASE = os.environ.get("AGENT_URL", "http://localhost:8000")
PASS_THRESHOLD = 0.8


def _stream_case(
    client: httpx.Client, token: str, conn: str, index: int, question: str, stamp: str
) -> dict:
    result: dict[str, Any] = {"rows": [], "answer": "", "sql": None, "chart": None, "error": None}
    with client.stream(
        "POST",
        f"{BASE}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "connection_id": conn,
            "thread_id": f"eval-{stamp}-{index}",
            "question": question,
        },
        timeout=120,
    ) as r:
        if r.status_code != 200:
            r.read()
            result["error"] = f"HTTP {r.status_code}"
            return result
        event = None
        for line in r.iter_lines():
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


def _is_number(value: Any) -> bool:
    """Numeric columns cross the wire as strings, because JSON cannot hold a Decimal."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _primary(case: dict, result: dict) -> bool:
    flat = [x for row in result["rows"] for x in row]
    if "expect_value" in case:
        return any(str(case["expect_value"]) in str(x) for x in flat)
    if "expect_contains" in case:
        haystack = result["answer"] + json.dumps(result["rows"], default=str)
        return str(case["expect_contains"]).lower() in haystack.lower()
    if "expect_type" in case:
        if case["expect_type"] == "number":
            return any(_is_number(x) for x in flat)
        if case["expect_type"] == "rows":
            return len(result["rows"]) > 0
    raise ValueError(f"case has no expectation: {case.get('q')!r}")


def _matches(case: dict, result: dict) -> bool:
    """`expect_chart` is an extra condition rather than a fourth kind, so a case can require
    both the right rows and the right picture."""
    if not _primary(case, result):
        return False
    if "expect_chart" in case:
        return bool(result.get("chart")) and result["chart"]["type"] == case["expect_chart"]
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="print SQL for failures")
    parser.add_argument("--cases", default="golden_sql.yaml")
    args = parser.parse_args()

    cases_path = Path(__file__).parent / args.cases

    try:
        token, conn = os.environ["TOKEN"], os.environ["CONN"]
    except KeyError as e:
        print(f"set {e.args[0]} in the environment", file=sys.stderr)
        return 2

    cases = yaml.safe_load(cases_path.read_text(encoding="utf-8")) or []
    if not cases:
        print(f"no cases in {cases_path}", file=sys.stderr)
        return 2

    # A fresh thread per invocation. The checkpointer keeps chat memory per thread, so reusing
    # `eval-0` lets a later run answer from the previous run's conversation without querying,
    # which silently inflates or deflates the score.
    stamp = uuid.uuid4().hex[:8]

    passed = 0
    with httpx.Client() as client:
        for i, case in enumerate(cases):
            result = _stream_case(client, token, conn, i, case["q"], stamp)
            ok = result["error"] is None and _matches(case, result)
            passed += ok
            print(f"{'PASS' if ok else 'FAIL'} | {case['q']}")
            if not ok and args.verbose:
                print(f"       sql:    {result['sql']}")
                print(f"       rows:   {result['rows'][:3]}")
                print(f"       error:  {result['error']}")

    rate = passed / len(cases)
    print(f"\n{passed}/{len(cases)} ({rate:.0%})")
    return 0 if rate >= PASS_THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())

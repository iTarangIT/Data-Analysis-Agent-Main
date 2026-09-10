"""Golden-question harness. Phase 1 is done at >= 80% (25 of 30).

    $env:TOKEN="..."; $env:CONN="..."; python evals/run_evals.py

Runs every case in golden_sql.yaml through the real SSE endpoint, so it exercises the router,
the generator, the guard, execution and the answer together.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

BASE = os.environ.get("AGENT_URL", "http://localhost:8000")
CASES_PATH = Path(__file__).parent / "golden_sql.yaml"
PASS_THRESHOLD = 0.8


def _stream_case(client: httpx.Client, token: str, conn: str, index: int, question: str) -> dict:
    result: dict[str, Any] = {"rows": [], "answer": "", "sql": None, "error": None}
    with client.stream(
        "POST",
        f"{BASE}/runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"connection_id": conn, "thread_id": f"eval-{index}", "question": question},
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
                elif event == "error":
                    result["error"] = data.get("message")
    return result


def _matches(case: dict, result: dict) -> bool:
    flat = [x for row in result["rows"] for x in row]
    if "expect_value" in case:
        return any(str(case["expect_value"]) in str(x) for x in flat)
    if "expect_contains" in case:
        haystack = result["answer"] + json.dumps(result["rows"], default=str)
        return str(case["expect_contains"]).lower() in haystack.lower()
    if "expect_type" in case:
        if case["expect_type"] == "number":
            return any(isinstance(x, int | float) and not isinstance(x, bool) for x in flat)
        if case["expect_type"] == "rows":
            return len(result["rows"]) > 0
    raise ValueError(f"case has no expectation: {case.get('q')!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="print SQL for failures")
    args = parser.parse_args()

    try:
        token, conn = os.environ["TOKEN"], os.environ["CONN"]
    except KeyError as e:
        print(f"set {e.args[0]} in the environment", file=sys.stderr)
        return 2

    cases = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8")) or []
    if not cases:
        print(f"no cases in {CASES_PATH}", file=sys.stderr)
        return 2

    passed = 0
    with httpx.Client() as client:
        for i, case in enumerate(cases):
            result = _stream_case(client, token, conn, i, case["q"])
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

"""Phase 4's done-line: killing a worker mid-run gives the client a clean `error` event.

    $env:TOKEN = python scripts/supabase_token.py you@example.com
    python scripts/check_killed_worker.py

TOKEN is a Supabase access token for an account that already has an organisation here; the
fixture connection is created in that organisation.

Needs Redis (Memurai on Windows) on the configured REDIS_URL, the App DB up, and a model key,
because it runs one real question. Everything else it starts and stops itself.

The manual runs this across four terminals. Doing it as one command makes the result repeatable
rather than a matter of hand-timing a kill, which matters here: a single-tool question finishes
in under two seconds, so a kill that takes a moment to land lets the run complete and the check
passes for entirely the wrong reason. Hence a question heavy enough to need several tool calls,
and a kill by tracked pid rather than a process lookup.

Ctrl-C would not do either. `loop.add_signal_handler` is unsupported on Windows, so arq
registers no signal handler and its shutdown waits for the running task: the run would finish
normally and the check would pass without ever testing anything.

Asserts three things: the stream ends with exactly one `error` event rather than hanging or
breaking mid-frame, the frames already published still arrive, and the run row is left in a
terminal state instead of `running` for ever.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

import httpx

REPO = pathlib.Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("CHECK_PORT", "8123"))
BASE = f"http://127.0.0.1:{PORT}"
LOGS = pathlib.Path(tempfile.gettempdir()) / "analyst-killcheck"

QUESTION = (
    "For each region give the revenue, the average units per order, and the single best "
    "selling product in that region. Then say which region leads and by how much."
)


def log(msg: str) -> None:
    print(f"[check] {msg}", flush=True)


def wait_for_health(timeout_s: float = 40) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{BASE}/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit("the server never came up; check the log in " + str(LOGS))


def make_connection(token: str) -> tuple[str, str]:
    """Register the sales fixture for the signed-in account, through the same app the server
    runs. Returns the connection id and the tenant it belongs to."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/auth/me", headers=headers)
    me.raise_for_status()
    body = (REPO / "evals" / "fixtures" / "sales.csv").read_bytes()
    r = client.post(
        "/connections/file",
        headers=headers,
        data={"name": "sales"},
        files={"files": ("sales.csv", body, "text/csv")},
    )
    r.raise_for_status()
    return r.json()["id"], me.json()["tenant_id"]


def kill_worker(pid: int) -> str:
    """Kill the worker we started, by pid, with its children.

    Deliberately not a process lookup: spawning PowerShell to find the worker costs the better
    part of a second, which is long enough for a short run to finish first.
    """
    cmd = (
        ["taskkill", "/F", "/T", "/PID", str(pid)]
        if sys.platform == "win32"
        else ["kill", "-9", str(pid)]
    )
    subprocess.run(cmd, capture_output=True, text=True, check=False)
    return str(pid)


def main() -> int:
    os.chdir(REPO)
    LOGS.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "QUEUE_ENABLED": "true", "PYTHONUNBUFFERED": "1"}

    token = os.environ.get("TOKEN")
    if not token:
        log("set TOKEN to a Supabase access token: python scripts/supabase_token.py <email>")
        return 2
    conn_id, tenant_id = make_connection(token)
    log(f"connection {conn_id}")

    with (
        open(LOGS / "server.log", "w") as server_log,
        open(LOGS / "worker.log", "w") as worker_log,
    ):
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
            cwd=REPO,
            env=env,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        worker = subprocess.Popen(
            [sys.executable, "-m", "arq", "app.workers.runs.WorkerSettings"],
            cwd=REPO,
            env=env,
            stdout=worker_log,
            stderr=subprocess.STDOUT,
        )

        events: list[tuple[str, str]] = []
        killed_pid = None
        try:
            wait_for_health()
            log("server up; giving the worker a moment to attach")
            time.sleep(4)

            with (
                httpx.Client(timeout=httpx.Timeout(120.0, read=120.0)) as client,
                client.stream(
                    "POST",
                    f"{BASE}/runs",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"connection_id": conn_id, "thread_id": "kill", "question": QUESTION},
                ) as r,
            ):
                log(f"POST /runs -> {r.status_code}")
                if r.status_code != 200:
                    log(f"body: {r.read()[:300]!r}")
                    return 1

                event = None
                for line in r.iter_lines():
                    if line.startswith("event:"):
                        event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:") and event:
                        events.append((event, line.split(":", 1)[1].strip()))
                        log(f"  <- {event}: {events[-1][1][:88]}")

                        # Kill on the first frame: it proves the worker had started the run, so
                        # this tests a lost worker rather than a job that never began.
                        if killed_pid is None:
                            killed_pid = kill_worker(worker.pid)
                            log(f"killed the worker mid-run: pid {killed_pid}")

                        if event in ("done", "error"):
                            break
                        event = None
        finally:
            for p in (worker, server):
                p.kill()

    kinds = [e for e, _ in events]
    log(f"events: {kinds}")

    ok = True
    if killed_pid is None:
        log("FAIL: the worker was never killed, so nothing was tested")
        ok = False
    if kinds.count("error") != 1 or kinds[-1:] != ["error"]:
        log(f"FAIL: expected exactly one trailing 'error', got {kinds[-1:]}")
        log("      a run that just finished means the kill lost the race; see the docstring")
        ok = False
    else:
        log(f"PASS: clean error event, {json.loads(events[-1][1]).get('message')!r}")

    from sqlalchemy import create_engine, text

    from app.config import get_settings

    engine = create_engine(str(get_settings().app_db_url))
    with engine.connect() as c:
        row = c.execute(
            text(
                "select id, status, error from runs where tenant_id = :t "
                "order by created_at desc limit 1"
            ),
            {"t": tenant_id},
        ).first()
    log(f"run row: status={row[1]!r} error={row[2]!r}")
    if row[1] == "running":
        log("FAIL: the run was left running for ever")
        ok = False

    log("phase 4 done-line: PASS" if ok else "phase 4 done-line: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

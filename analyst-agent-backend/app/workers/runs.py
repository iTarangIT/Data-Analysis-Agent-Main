"""The arq worker that executes a run and publishes its frames.

    $env:QUEUE_ENABLED="true"; arq app.workers.runs.WorkerSettings

On Windows, Ctrl-C does not stop an in-flight job: `loop.add_signal_handler` is unsupported, so
arq registers no handler and its shutdown waits for running tasks. Use `Stop-Process -Force` to
test what a lost worker looks like.
"""

import asyncio
from typing import Any, ClassVar

from arq import cron, func

from app import queue
from app.config import get_settings
from app.connectors.registry import connector_for
from app.db.models import Connection, Run
from app.db.session import SessionLocal
from app.llm import configure_tracing
from app.logging import configure_logging, log
from app.mcp_client import probe_mcp
from app.services import runs as svc
from app.services import tables


async def _heartbeat(ctx: dict, run_id: str) -> None:
    """Prove the worker is alive while the agent runs.

    arq's own in-progress key is set once with a TTL of the job timeout plus ten seconds and is
    never refreshed, so a killed worker would take minutes to notice. The first beat is sent
    immediately, so "queued but never started" and "started then died" differ from the outset.
    """
    interval = get_settings().run_heartbeat_s
    while True:
        await queue.publish(ctx["redis"], run_id, queue.HEARTBEAT)
        await asyncio.sleep(interval)


async def run_question(ctx: dict, run_id: str) -> None:
    """Execute one run, streaming its frames into `run:<id>`.

    `execute_run` must go through `asyncio.to_thread`. Running it inline would block this
    coroutine, the heartbeat would stop for the length of the model call, and every long run
    would be reported to the client as a dead worker.
    """
    redis = ctx["redis"]
    loop = asyncio.get_running_loop()
    db = SessionLocal()

    def emit(event: dict) -> None:
        asyncio.run_coroutine_threadsafe(
            queue.publish(redis, run_id, svc.sse_frame(event)), loop
        ).result()

    beat = asyncio.create_task(_heartbeat(ctx, run_id))
    try:
        run = db.get(Run, run_id)
        if run is None:
            log.warning("worker.run_missing", run_id=run_id)
            return
        conn = db.get(Connection, run.connection_id)
        connector = connector_for(conn)
        # Read from the store, not the source: `prepare_run` has just brought it up to date.
        catalog = await tables.load_for_run(db, conn, connector)
        await asyncio.to_thread(svc.execute_run, db, run, connector, catalog, emit)
    except asyncio.CancelledError:
        # The client went away, or the job timed out. Report it before the task dies, using the
        # synchronous client: an await inside an already-cancelled coroutine may never resume.
        svc.abandon_run(db, run_id, "run cancelled")
        _publish_sync(
            run_id, svc.sse_frame({"type": "error", "data": {"message": "run cancelled"}})
        )
        raise
    finally:
        beat.cancel()
        db.close()


def _publish_sync(run_id: str, frame: dict[str, str]) -> None:
    import redis as redis_sync

    s = get_settings()
    client = redis_sync.Redis.from_url(str(s.redis_url), decode_responses=True)
    try:
        client.xadd(queue.stream_key(run_id), frame, maxlen=2000, approximate=True)
        client.expire(queue.stream_key(run_id), s.run_stream_ttl_s)
    finally:
        client.close()


async def reap_stale(ctx: dict) -> None:
    db = SessionLocal()
    try:
        svc.reap_stale_runs(db)
    finally:
        db.close()


async def _startup(ctx: dict) -> None:
    # The worker does not go through the app's lifespan, so nothing else configures logging or
    # tracing. Without the second, every queued run went untraced.
    configure_logging()
    configure_tracing()
    if get_settings().mcp_startup_probe:
        await probe_mcp()
    log.info("worker.startup", max_jobs=get_settings().worker_max_jobs)


class WorkerSettings:
    # max_tries=1: a failed run must never be retried, or it spends a tenant's tokens twice
    # and streams to a client that has already been told what happened.
    functions: ClassVar[list[Any]] = [
        func(run_question, name="run_question", max_tries=1, timeout=get_settings().run_timeout_s)
    ]
    cron_jobs: ClassVar[list[Any]] = [cron(reap_stale, minute=None, run_at_startup=True)]
    redis_settings = queue.redis_settings()
    max_jobs = get_settings().worker_max_jobs
    allow_abort_jobs = True
    # Results travel through the stream, so arq's own result keys are dead weight.
    keep_result = 0
    on_startup = _startup

"""The queued transport: frames in, identical frames out, and a dead worker that ends cleanly.

Runs against fakeredis, so the suite needs no Redis. `QUEUE_ENABLED` defaults to false, so no
other test touches any of this.
"""

import asyncio
import json
from datetime import date
from decimal import Decimal

import fakeredis.aioredis
import pytest

from app import queue
from app.services.runs import sse_frame

RUN_ID = "r1"

EVENTS = [
    {"type": "status", "data": {"stage": "router"}},
    {"type": "status", "data": {"stage": "sql_gen"}},
    {"type": "status", "data": {"stage": "sql_guard"}},
    {"type": "sql", "data": {"sql": "SELECT 1 LIMIT 500"}},
    {"type": "status", "data": {"stage": "db_exec"}},
    {
        "type": "rows",
        "data": {"columns": ["total"], "rows": [[Decimal("266300.00")]], "truncated": False},
    },
    {"type": "status", "data": {"stage": "answer"}},
    {"type": "token", "data": {"text": "Two hundred and sixty six thousand."}},
    {"type": "done", "data": {"run_id": RUN_ID, "duration_ms": 12}},
]


@pytest.fixture
def redis():
    # decode_responses=False, matching arq's real pool. With True these tests passed while
    # every queued run against real Redis silently reported a dead worker.
    return fakeredis.aioredis.FakeRedis(decode_responses=False)


@pytest.fixture
def fast(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "run_heartbeat_s", 0.05, raising=False)
    monkeypatch.setattr(s, "run_stall_timeout_s", 0.4, raising=False)
    return s


async def _drain(redis) -> list[dict]:
    return [frame async for frame in queue.consume(redis, RUN_ID)]


class TestFrameIdentity:
    def test_a_frame_is_valid_as_both_a_stream_entry_and_an_sse_event(self):
        frame = sse_frame(EVENTS[5])

        assert set(frame) == {"event", "data"}
        assert all(isinstance(v, str) for v in frame.values()), "xadd takes strings only"

    def test_decimal_and_date_survive_the_encoder(self):
        frame = sse_frame(
            {"type": "rows", "data": {"v": Decimal("266300.00"), "d": date(2026, 9, 10)}}
        )

        assert json.loads(frame["data"]) == {"v": "266300.00", "d": "2026-09-10"}

    async def test_what_comes_back_is_byte_identical_to_what_went_in(self, redis, fast):
        for event in EVENTS:
            await queue.publish(redis, RUN_ID, sse_frame(event))

        assert await _drain(redis) == [sse_frame(e) for e in EVENTS]


class TestStreamLifetime:
    async def test_it_stops_at_the_terminal_frame(self, redis, fast):
        for event in EVENTS:
            await queue.publish(redis, RUN_ID, sse_frame(event))
        await queue.publish(redis, RUN_ID, sse_frame({"type": "token", "data": {"text": "late"}}))

        frames = await _drain(redis)

        assert frames[-1]["event"] == "done"
        assert len(frames) == len(EVENTS), "nothing after `done` is delivered"

    async def test_an_error_frame_also_ends_the_stream(self, redis, fast):
        await queue.publish(redis, RUN_ID, sse_frame(EVENTS[0]))
        await queue.publish(redis, RUN_ID, sse_frame({"type": "error", "data": {"message": "no"}}))

        frames = await _drain(redis)

        assert [f["event"] for f in frames] == ["status", "error"]

    async def test_the_key_expires_so_a_finished_run_does_not_accumulate(self, redis, fast):
        await queue.publish(redis, RUN_ID, sse_frame(EVENTS[0]))

        assert await redis.ttl(queue.stream_key(RUN_ID)) > 0


class TestDeadWorker:
    async def test_a_worker_that_stops_beating_raises_rather_than_hanging(self, redis, fast):
        """The done-line in unit form: no terminal frame and no heartbeat means the run is dead."""
        await queue.publish(redis, RUN_ID, sse_frame(EVENTS[0]))

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(_drain(redis), timeout=5)

    async def test_a_slow_run_survives_while_heartbeats_arrive(self, redis, fast):
        """Guards the regression where the worker runs the agent inline in its own coroutine:
        the heartbeat stops during the model call and every long run looks dead."""

        async def beat_then_finish():
            for _ in range(12):
                await queue.publish(redis, RUN_ID, queue.HEARTBEAT)
                await asyncio.sleep(0.05)
            await queue.publish(redis, RUN_ID, sse_frame(EVENTS[-1]))

        await queue.publish(redis, RUN_ID, sse_frame(EVENTS[0]))
        task = asyncio.create_task(beat_then_finish())
        frames = await _drain(redis)
        await task

        assert [f["event"] for f in frames] == ["status", "done"]

    async def test_heartbeats_never_reach_the_client(self, redis, fast):
        await queue.publish(redis, RUN_ID, queue.HEARTBEAT)
        await queue.publish(redis, RUN_ID, sse_frame(EVENTS[0]))
        await queue.publish(redis, RUN_ID, queue.HEARTBEAT)
        await queue.publish(redis, RUN_ID, sse_frame(EVENTS[-1]))

        frames = await _drain(redis)

        assert [f["event"] for f in frames] == ["status", "done"]
        assert all("hb" not in f for f in frames)


class TestAbort:
    async def test_it_marks_the_run_for_the_worker_to_stop(self, redis):
        from arq.constants import abort_jobs_ss

        await queue.request_abort(redis, RUN_ID)

        assert await redis.zscore(abort_jobs_ss, RUN_ID) is not None


class TestWorkerSettings:
    """Nothing in the service imports the worker module, so without this a typo in it would
    only surface when someone actually starts a worker."""

    def test_the_worker_module_is_importable_and_wired(self):
        from app.workers.runs import WorkerSettings, run_question, sync_dataset

        assert [f.name for f in WorkerSettings.functions] == ["run_question", "sync_dataset"]
        assert WorkerSettings.functions[0].coroutine is run_question
        assert WorkerSettings.functions[1].coroutine is sync_dataset
        assert WorkerSettings.functions[1].max_tries == 1
        assert callable(WorkerSettings.on_startup)

    def test_a_failed_run_is_never_retried(self):
        from app.workers.runs import WorkerSettings

        # A retry would spend the tenant's tokens twice and stream to a client that has already
        # been told what happened.
        assert WorkerSettings.functions[0].max_tries == 1

    def test_results_are_not_kept_because_they_travel_through_the_stream(self):
        from app.workers.runs import WorkerSettings

        assert WorkerSettings.keep_result == 0

    def test_aborting_is_enabled_so_an_abandoned_run_stops_spending_quota(self):
        from app.workers.runs import WorkerSettings

        assert WorkerSettings.allow_abort_jobs is True

    def test_concurrency_is_bounded_by_the_database_pool_not_arqs_default(self):
        from app.config import get_settings
        from app.workers.runs import WorkerSettings

        # Each job holds an App DB session, a checkpoint connection and a customer DB
        # connection, against a pool of 5 plus 10 overflow. arq's own default is 10.
        assert WorkerSettings.max_jobs == get_settings().worker_max_jobs
        assert WorkerSettings.max_jobs < 10

    def test_arq_does_not_pull_in_uvloop_which_has_no_windows_support(self):
        import pathlib

        import arq

        root = pathlib.Path(arq.__file__).parent
        hits = [p.name for p in root.rglob("*.py") if "uvloop" in p.read_text(errors="ignore")]
        assert hits == [], "arq gained a uvloop dependency; the worker will not start on Windows"

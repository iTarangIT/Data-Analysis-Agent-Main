"""The Redis side of a queued run: one stream per run, carrying the SSE frames themselves.

Streams rather than pub/sub because pub/sub drops anything published before the reader
attaches, and there is an unavoidable gap between enqueuing a run and subscribing to it. A
list would work for ordering but is destructive, so a reconnecting client could never resume.
"""

import time
from collections.abc import AsyncIterator
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings
from app.logging import log

# A heartbeat carries no `event` field, so a consumer that yields only frames with one cannot
# leak it into the frozen contract.
HEARTBEAT = {"hb": "1"}

_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(str(get_settings().redis_url))


def stream_key(run_id: str) -> str:
    return f"run:{run_id}"


async def connect() -> ArqRedis:
    """Opened at startup when the queue is on, so a stopped Memurai fails the boot rather than
    the first question."""
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
        log.info("queue.connected", url=str(get_settings().redis_url))
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


def pool() -> ArqRedis:
    if _pool is None:
        raise RuntimeError("queue is enabled but was never connected")
    return _pool


async def publish(redis: Any, run_id: str, frame: dict[str, str]) -> None:
    key = stream_key(run_id)
    s = get_settings()
    await redis.xadd(key, frame, maxlen=2000, approximate=True)
    await redis.expire(key, s.run_stream_ttl_s)


async def consume(redis: Any, run_id: str) -> AsyncIterator[dict[str, str]]:
    """Yield the run's frames until it ends, or until the worker stops proving it is alive.

    Any entry resets the stall clock, heartbeats included. When the clock runs out the run is
    treated as dead: the caller emits one error frame rather than leaving the client hanging.
    """
    s = get_settings()
    key = stream_key(run_id)
    last = "0-0"
    idle = 0.0

    while idle < s.run_stall_timeout_s:
        t0 = time.monotonic()
        batch = await redis.xread({key: last}, block=int(s.run_heartbeat_s * 1000), count=100)
        if not batch:
            idle += time.monotonic() - t0
            continue

        idle = 0.0
        for _, entries in batch:
            for entry_id, fields in entries:
                last = entry_id
                if "event" not in fields:
                    continue
                yield fields
                if fields["event"] in ("done", "error"):
                    return

    log.warning("queue.stalled", run_id=run_id, after_s=s.run_stall_timeout_s)
    raise TimeoutError("the run stopped responding")


async def request_abort(redis: Any, run_id: str) -> None:
    """Stop a run whose client has gone away.

    `Job.abort()` is not used: it ends by awaiting a result this service deliberately does not
    keep, and with no timeout it waits forever. The marker is all the worker reads.
    """
    from arq.constants import abort_jobs_ss

    await redis.zadd(abort_jobs_ss, {run_id: int(time.time() * 1000)})

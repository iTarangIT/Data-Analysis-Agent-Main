import multiprocessing
import os
import sys
from collections.abc import Callable
from multiprocessing.process import BaseProcess
from typing import Any

from app.config import get_settings
from app.logging import log
from app.services.errors import DomainError

if sys.platform == "win32":
    from multiprocessing.connection import PipeConnection as Channel
else:
    from multiprocessing.connection import Connection as Channel


def _serve(conn: Channel, memory_mb: int) -> None:
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    if sys.platform != "win32":
        import resource

        limit = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    while (job := conn.recv()) is not None:
        fn, args = job
        try:
            conn.send(("ok", fn(*args)))
        except MemoryError:
            conn.send(("memory", ""))
        except DomainError as e:
            conn.send(("refused", str(e)))
        except Exception as e:
            conn.send(("error", f"{type(e).__name__}: {e}"))


class Sandbox:
    def __init__(self) -> None:
        self._process: BaseProcess | None = None
        self._conn: Channel | None = None

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop()

    def _start(self) -> Channel:
        if self._conn is None:
            context = multiprocessing.get_context("spawn")
            parent, child = context.Pipe()
            self._process = context.Process(
                target=_serve, args=(child, get_settings().ingest_memory_mb), daemon=True
            )
            self._process.start()
            child.close()
            self._conn = parent
        return self._conn

    def _stop(self) -> None:
        if self._process is not None:
            self._process.kill()
            self._process.join()
        if self._conn is not None:
            self._conn.close()
        self._process = self._conn = None

    def run(self, name: str, fn: Callable[..., Any], *args: Any) -> Any:
        conn = self._start()
        conn.send((fn, args))
        if not conn.poll(get_settings().ingest_timeout_s):
            self._stop()
            raise DomainError(f"{name} took too long to read")
        try:
            status, value = conn.recv()
        except EOFError:
            self._stop()
            raise DomainError(f"{name} is too large to read") from None
        if status == "ok":
            return value
        if status == "memory":
            self._stop()
            raise DomainError(f"{name} is too large to read")
        if status == "refused":
            raise DomainError(value)
        log.warning("upload.ingest_failed", file=name, error=value)
        raise DomainError(f"{name} could not be read as a spreadsheet")

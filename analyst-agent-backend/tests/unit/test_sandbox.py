import os
import sys
import time

import pytest

from app.connectors.sandbox import Sandbox
from app.services.errors import DomainError


def _exhaust() -> None:
    raise MemoryError


def _die() -> None:
    os._exit(1)


def _refuse() -> None:
    raise DomainError("book.xlsx has no readable rows")


def _break() -> None:
    raise KeyError("sheet")


def _allocate(size: int) -> int:
    return len(bytearray(size))


@pytest.fixture
def limits(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "ingest_timeout_s", 30, raising=False)
    return get_settings()


def test_a_result_comes_back_from_the_child(limits):
    with Sandbox() as sandbox:
        assert sandbox.run("sum.csv", sum, [1, 2, 3]) == 6
        assert sandbox.run("max.csv", max, [1, 2, 3]) == 3


def test_a_hung_parse_is_killed_at_the_timeout(limits, monkeypatch):
    monkeypatch.setattr(limits, "ingest_timeout_s", 1, raising=False)

    with Sandbox() as sandbox:
        sandbox.run("warm.csv", sum, [1])
        child = sandbox._process
        t0 = time.monotonic()

        with pytest.raises(DomainError, match=r"slow\.csv took too long to read"):
            sandbox.run("slow.csv", time.sleep, 30)

        assert time.monotonic() - t0 < 15
        assert child is not None and not child.is_alive()
        assert sandbox.run("next.csv", sum, [2]) == 2


def test_running_out_of_memory_is_a_domain_error(limits):
    with Sandbox() as sandbox, pytest.raises(DomainError, match=r"big\.xlsx is too large"):
        sandbox.run("big.xlsx", _exhaust)


def test_a_child_that_dies_is_reported_rather_than_waited_on(limits):
    with Sandbox() as sandbox, pytest.raises(DomainError, match=r"big\.xlsx is too large"):
        sandbox.run("big.xlsx", _die)


def test_a_refusal_keeps_its_own_words(limits):
    with Sandbox() as sandbox, pytest.raises(DomainError, match="has no readable rows"):
        sandbox.run("book.xlsx", _refuse)


def test_anything_else_is_a_file_that_could_not_be_read(limits):
    with (
        Sandbox() as sandbox,
        pytest.raises(DomainError, match=r"^odd\.xlsx could not be read as a spreadsheet$"),
    ):
        sandbox.run("odd.xlsx", _break)


@pytest.mark.skipif(sys.platform == "win32", reason="RLIMIT_AS is POSIX only")
def test_the_address_space_limit_stops_an_oversized_parse(limits, monkeypatch):
    monkeypatch.setattr(limits, "ingest_memory_mb", 1024, raising=False)

    with Sandbox() as sandbox, pytest.raises(DomainError, match="too large"):
        sandbox.run("huge.csv", _allocate, 4 * 1024**3)

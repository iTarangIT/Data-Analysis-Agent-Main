"""The model loads once per process, at startup, and only where tools actually run."""

from unittest.mock import AsyncMock, patch

import pytest

from app import main
from app.config import get_settings


@pytest.fixture
def settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "mcp_startup_probe", False)
    return s


async def _boot():
    with (
        patch.object(main, "load_forecaster") as load,
        patch.object(main, "setup_store"),
        patch.object(main, "SessionLocal"),
        patch.object(main, "reap_stale_runs"),
        patch.object(main.queue, "connect", AsyncMock()),
        patch.object(main.queue, "close", AsyncMock()),
    ):
        async with main.lifespan(main.app):
            pass
    return load


class TestTheApi:
    async def test_switched_on_it_loads_the_model_at_boot(self, settings, monkeypatch):
        monkeypatch.setattr(settings, "forecast_engine", "timesfm")

        load = await _boot()

        load.assert_called_once_with()

    async def test_switched_off_it_loads_nothing(self, settings, monkeypatch):
        monkeypatch.setattr(settings, "forecast_engine", "off")

        (await _boot()).assert_not_called()

    async def test_in_queue_mode_it_leaves_the_model_to_the_worker(self, settings, monkeypatch):
        # The API runs no tools when the queue is on, so a gigabyte there would be dead weight.
        monkeypatch.setattr(settings, "forecast_engine", "timesfm")
        monkeypatch.setattr(settings, "queue_enabled", True)

        (await _boot()).assert_not_called()


class TestTheWorker:
    async def test_switched_on_the_worker_loads_the_model(self, settings, monkeypatch):
        from app.workers.runs import _startup

        monkeypatch.setattr(settings, "forecast_engine", "timesfm")
        with patch("app.workers.runs.load_forecaster") as load:
            await _startup({})

        load.assert_called_once_with()

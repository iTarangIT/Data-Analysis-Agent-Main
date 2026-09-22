"""The service around a model, driven by stand-in engines so no weights are loaded."""

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.forecasting import service
from app.forecasting.engine import EngineForecast
from app.forecasting.preprocessing import ForecastInputError, Series
from app.forecasting.service import ForecastEngineError, ForecastService


class RecordingEngine:
    """Forecasts a ramp from the last value and keeps what it was given."""

    name = "recording"
    max_context = 1024
    max_horizon = 256

    def __init__(self):
        self.seen: list[np.ndarray] = []

    def predict(self, values, horizon):
        self.seen.append(values)
        mean = values[-1] + np.arange(1, horizon + 1, dtype=np.float64)
        return EngineForecast(mean=mean, lower=mean - 1, upper=mean + 1)


def series(n: int = 12, end: str = "2026-08", freq: str = "M", grain: str = "month") -> Series:
    return Series(
        periods=pd.period_range(end=end, periods=n, freq=freq),
        values=np.arange(n, dtype=np.float64),
        grain=grain,
        kind="total",
        filled=0,
        merged=0,
        dropped_partial=None,
        capped=False,
    )


class TestForecast:
    def test_the_future_periods_follow_on_and_roll_over_the_year(self):
        forecast = ForecastService(RecordingEngine()).forecast(series(end="2026-11"), 3)

        assert forecast.periods == ["2026-12", "2027-01", "2027-02"]

    def test_quarters_roll_over_too(self):
        forecast = ForecastService(RecordingEngine()).forecast(
            series(end="2026Q3", freq="Q", grain="quarter"), 2
        )

        assert forecast.periods == ["2026Q4", "2027Q1"]

    def test_only_the_latest_context_reaches_the_engine(self):
        engine = RecordingEngine()
        engine.max_context = 4

        ForecastService(engine).forecast(series(12), 1)

        assert engine.seen[0].tolist() == [8.0, 9.0, 10.0, 11.0]

    def test_no_further_ahead_than_the_history_goes_back(self):
        with pytest.raises(ForecastInputError) as caught:
            ForecastService(RecordingEngine()).forecast(series(12), 13)

        assert (caught.value.code, caught.value.fixable) == ("horizon_too_long", False)

    def test_no_further_ahead_than_the_model_can_see(self):
        engine = RecordingEngine()
        engine.max_horizon = 4

        with pytest.raises(ForecastInputError) as caught:
            ForecastService(engine).forecast(series(12), 5)

        assert caught.value.code == "horizon_too_long"

    def test_a_failing_model_is_an_engine_error(self):
        engine = RecordingEngine()
        engine.predict = lambda values, horizon: 1 / 0

        with pytest.raises(ForecastEngineError):
            ForecastService(engine).forecast(series(), 2)

    def test_a_model_returning_nan_is_an_engine_error(self):
        engine = RecordingEngine()
        nan = np.array([np.nan])
        engine.predict = lambda values, horizon: EngineForecast(mean=nan, lower=nan, upper=nan)

        with pytest.raises(ForecastEngineError):
            ForecastService(engine).forecast(series(), 1)

    def test_both_views_are_plain_json(self):
        forecast = ForecastService(RecordingEngine()).forecast(series(), 2)

        summary = json.loads(json.dumps(forecast.summary()))
        chart = json.loads(json.dumps(forecast.chart_payload()))

        assert summary["points"][0] == {
            "period": "2026-09", "forecast": 12.0, "low": 11.0, "high": 13.0,
        }  # fmt: skip
        assert summary["history"]["from"] == "2025-09" and summary["history"]["to"] == "2026-08"
        assert summary["interval"] == "80%" and summary["model"] == "recording"
        assert chart["history"][-1] == ["2026-08", 11.0]
        assert chart["points"][1] == ["2026-10", 13.0, 12.0, 14.0]
        assert all(type(v) is float for v in forecast.mean)


class TestOneModelPerProcess:
    @pytest.fixture(autouse=True)
    def fresh(self, monkeypatch):
        monkeypatch.setattr(service, "_service", None)

    def _settings(self, monkeypatch, engine: str):
        settings = SimpleNamespace(
            forecast_engine=engine, forecast_checkpoint="ckpt", forecast_threads=2
        )
        monkeypatch.setattr(service, "get_settings", lambda: settings)

    def test_switched_off_nothing_is_built(self, monkeypatch):
        self._settings(monkeypatch, "off")
        monkeypatch.setattr(service, "TimesFMEngine", pytest.fail)

        service.load_forecaster()

        assert service.get_forecaster() is None

    def test_switched_on_the_model_is_built_once(self, monkeypatch):
        self._settings(monkeypatch, "timesfm")
        built = []
        monkeypatch.setattr(
            service,
            "TimesFMEngine",
            lambda checkpoint, threads: built.append(1) or RecordingEngine(),
        )

        service.load_forecaster()
        service.load_forecaster()

        assert len(built) == 1
        assert isinstance(service.get_forecaster(), ForecastService)

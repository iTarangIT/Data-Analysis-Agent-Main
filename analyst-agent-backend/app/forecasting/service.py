"""One forecasting model per process, and the single way into it."""

import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.config import get_settings
from app.forecasting.engine import ForecastEngine, TimesFMEngine
from app.forecasting.preprocessing import ForecastInputError, Series, label

# The band between the 10th and 90th percentiles.
INTERVAL = 0.8


class ForecastEngineError(Exception):
    """The model itself failed, as opposed to the data being unfit for it."""


def _floats(values: np.ndarray) -> list[float]:
    # Plain floats: numpy scalars break json.dumps, and the chart is saved to a JSON column.
    return [round(float(v), 4) for v in values]


@dataclass(frozen=True)
class Forecast:
    history: Series
    periods: list[str]
    mean: list[float]
    lower: list[float]
    upper: list[float]
    model: str

    def summary(self) -> dict[str, Any]:
        """What the model is told: enough to explain the forecast, not the whole history."""
        h = self.history
        return {
            "grain": h.grain,
            "kind": h.kind,
            "horizon": len(self.periods),
            "interval": f"{INTERVAL:.0%}",
            "history": {
                "periods": len(h),
                "from": label(h.periods[0]),
                "to": label(h.periods[-1]),
                "last_value": round(float(h.values[-1]), 4),
                "filled_gaps": h.filled,
                "dropped_partial": h.dropped_partial,
                "capped": h.capped,
            },
            "points": [
                {"period": p, "forecast": m, "low": lo, "high": hi}
                for p, m, lo, hi in zip(
                    self.periods, self.mean, self.lower, self.upper, strict=True
                )
            ],
            "model": self.model,
        }

    def chart_payload(self) -> dict[str, Any]:
        return {
            "grain": self.history.grain,
            "interval": INTERVAL,
            "history": [
                [label(p), v]
                for p, v in zip(self.history.periods, _floats(self.history.values), strict=True)
            ],
            "points": [
                [p, m, lo, hi]
                for p, m, lo, hi in zip(
                    self.periods, self.mean, self.lower, self.upper, strict=True
                )
            ],
        }


class ForecastService:
    def __init__(self, engine: ForecastEngine):
        self._engine = engine
        # Tools run on worker threads, and two torch calls at once only fight over the same
        # cores. One short series takes well under a second, so a queue beats contention.
        self._lock = threading.Lock()

    def forecast(self, series: Series, horizon: int) -> Forecast:
        longest = min(self._engine.max_horizon, len(series))
        if horizon > longest:
            raise ForecastInputError(
                "horizon_too_long",
                f"{horizon} {series.grain}s ahead is further than {len(series)} {series.grain}s "
                f"of history can support; the most is {longest}.",
                fixable=False,
            )

        try:
            with self._lock:
                out = self._engine.predict(series.values[-self._engine.max_context :], horizon)
        except Exception as e:
            raise ForecastEngineError(str(e)) from e
        if not all(np.isfinite(a).all() for a in (out.mean, out.lower, out.upper)):
            raise ForecastEngineError("the model returned a value that is not a number")

        last = series.periods[-1]
        return Forecast(
            history=series,
            periods=[label(last + step) for step in range(1, horizon + 1)],
            mean=_floats(out.mean),
            lower=_floats(out.lower),
            upper=_floats(out.upper),
            model=self._engine.name,
        )


_service: ForecastService | None = None


def load_forecaster() -> None:
    """Build the model once per process. Called at startup, never per request."""
    global _service
    s = get_settings()
    if s.forecast_engine == "off" or _service is not None:
        return
    _service = ForecastService(TimesFMEngine(s.forecast_checkpoint, s.forecast_threads))


def get_forecaster() -> ForecastService | None:
    return _service

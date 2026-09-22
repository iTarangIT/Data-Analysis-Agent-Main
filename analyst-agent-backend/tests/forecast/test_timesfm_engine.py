"""The real checkpoint. Slow and about a gigabyte, so it runs only under `-m forecast`."""

import numpy as np
import pytest

pytest.importorskip("timesfm")

from app.forecasting.engine import TimesFMEngine

pytestmark = pytest.mark.forecast


@pytest.fixture(scope="module")
def engine():
    return TimesFMEngine("google/timesfm-2.5-200m-pytorch", threads=2)


def seasonal(n: int) -> np.ndarray:
    t = np.arange(n, dtype=np.float64)
    return 100 + 0.5 * t + 20 * np.sin(2 * np.pi * t / 12)


def test_it_returns_one_ordered_range_per_period(engine):
    out = engine.predict(seasonal(48), 12)

    assert out.mean.shape == out.lower.shape == out.upper.shape == (12,)
    assert np.all(out.lower <= out.mean + 1e-6)
    assert np.all(out.mean <= out.upper + 1e-6)


def test_it_beats_repeating_last_year(engine):
    history, actual = seasonal(60)[:48], seasonal(60)[48:]

    out = engine.predict(history, 12)

    assert np.abs(out.mean - actual).mean() < np.abs(history[-12:] - actual).mean()

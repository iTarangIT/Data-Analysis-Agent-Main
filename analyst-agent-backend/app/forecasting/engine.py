"""The forecasting model, behind the one interface the rest of the service knows.

`ForecastEngine` is all the service calls. `TimesFMEngine` is the only code that touches
TimesFM or torch, and it imports them when it is built, so with forecasting switched off
neither is ever loaded. Another model means another class here, and nothing else changes.
"""

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class EngineForecast:
    mean: np.ndarray
    lower: np.ndarray
    upper: np.ndarray


class ForecastEngine(Protocol):
    name: str
    max_context: int
    max_horizon: int

    def predict(self, values: np.ndarray, horizon: int) -> EngineForecast: ...


# TimesFM's quantile head returns the mean, then the 10th to 90th percentiles.
P10, P90 = 1, 9


class TimesFMEngine:
    name = "timesfm-2.5-200m"
    max_context = 1024
    max_horizon = 256

    def __init__(self, checkpoint: str, threads: int):
        import timesfm
        import torch

        torch.set_num_threads(threads)
        # No torch_compile: it needs a C++ toolchain on Windows and buys little for one short
        # series on a CPU.
        self._model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
            checkpoint, torch_compile=False
        )
        self._model.compile(
            timesfm.ForecastConfig(
                max_context=self.max_context,
                max_horizon=self.max_horizon,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
                force_flip_invariance=True,
                infer_is_positive=True,
                fix_quantile_crossing=True,
            )
        )
        # The first forecast pays for lazy initialisation. Better at boot than on a question.
        self.predict(np.arange(32, dtype=np.float64), 1)

    def predict(self, values: np.ndarray, horizon: int) -> EngineForecast:
        point, quantiles = self._model.forecast(horizon=horizon, inputs=[values])
        return EngineForecast(mean=point[0], lower=quantiles[0, :, P10], upper=quantiles[0, :, P90])

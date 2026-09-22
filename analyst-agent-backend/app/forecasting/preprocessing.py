"""A query's rows turned into the clean, evenly spaced series a forecasting model needs.

Nothing here knows about SQL, connectors or models. It takes columns and rows and returns
numbers, or says in words why it cannot, and whether a different call would fix it.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

import numpy as np
import pandas as pd

Grain = Literal["hour", "day", "week", "month", "quarter", "year"]
Kind = Literal["total", "level"]

# Weeks end on Sunday, so each one starts on the Monday that date_trunc('week') returns.
FREQ: dict[str, str] = {
    "hour": "h",
    "day": "D",
    "week": "W-SUN",
    "month": "M",
    "quarter": "Q",
    "year": "Y",
}

MIN_HISTORY = 8
# Past this the grain is finer than the data, and a filled series is mostly invention.
MAX_MISSING_SHARE = 0.3


class ForecastInputError(Exception):
    """Why a series cannot be forecast, in words the model can pass on.

    `fixable` separates a call the model got wrong from data that cannot support a forecast,
    so the model knows whether to call again or to explain.
    """

    def __init__(self, code: str, message: str, fixable: bool):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fixable = fixable


@dataclass(frozen=True)
class Series:
    periods: pd.PeriodIndex
    values: np.ndarray
    grain: Grain
    kind: Kind
    filled: int
    merged: int
    dropped_partial: str | None
    capped: bool

    def __len__(self) -> int:
        return len(self.values)


def label(period: pd.Period) -> str:
    freq = period.freqstr
    if freq.startswith("W"):
        # A week prints as its whole range; its Monday is what the SQL grouped on.
        return period.start_time.date().isoformat()
    if freq == "h":
        return period.start_time.isoformat(timespec="minutes")
    return str(period)


def _timestamp(value: Any) -> date | datetime:
    """Naive wall-clock time. A UTC conversion would move a local-midnight month bucket into
    the previous month, and pandas refuses a column whose offsets change at DST."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return value
    raise ValueError(value)


def prepare_series(
    columns: list[str],
    rows: list,
    time_column: str,
    value_column: str,
    grain: Grain,
    kind: Kind,
    today: date,
    capped: bool = False,
) -> Series:
    """`capped` means the query returned more rows than these. They must then be newest
    first, so what was cut off is the oldest history rather than the most recent."""
    for name in (time_column, value_column):
        if name not in columns:
            raise ForecastInputError(
                "missing_column",
                f"The result has no column called {name}. It has: {', '.join(columns)}.",
                fixable=True,
            )

    t, v = columns.index(time_column), columns.index(value_column)
    pairs = [(row[t], row[v]) for row in rows if row[t] is not None and row[v] is not None]
    if not pairs:
        raise ForecastInputError(
            "empty", "The query returned no history to forecast from.", fixable=False
        )

    times, raw = zip(*pairs, strict=True)
    try:
        stamps = pd.DatetimeIndex([_timestamp(x) for x in times])
    except (TypeError, ValueError):
        raise ForecastInputError(
            "bad_timestamps", f"{time_column} does not hold dates or times.", fixable=True
        ) from None

    if capped and stamps[0] < stamps[-1]:
        raise ForecastInputError(
            "wrong_order",
            f"More periods came back than can be used, oldest first, so the most recent were "
            f"cut off. Order by {time_column} descending.",
            fixable=True,
        )

    values = pd.to_numeric(pd.Series(raw, dtype=object), errors="coerce")
    if values.isna().any():
        example = raw[int(values.isna().to_numpy().argmax())]
        raise ForecastInputError(
            "not_numeric", f"{value_column} is not a number, e.g. {example!r}.", fixable=True
        )

    series = pd.Series(values.to_numpy(dtype=np.float64), index=stamps.to_period(FREQ[grain]))
    merged = len(series) - series.index.nunique()
    if capped and merged:
        raise ForecastInputError(
            "not_grouped",
            f"More than one row came back per {grain} and the result was cut off, so the oldest "
            f"{grain} is incomplete. Group by {grain} in the SQL.",
            fixable=True,
        )
    by_period = series.groupby(level=0)
    series = by_period.sum() if kind == "total" else by_period.mean()

    dropped = None
    last = series.index[-1]
    if last.start_time.date() <= today <= last.end_time.date():
        dropped = label(last)
        series = series.iloc[:-1]

    span = (
        pd.period_range(series.index[0], series.index[-1], freq=FREQ[grain])
        if len(series)
        else pd.PeriodIndex([], freq=FREQ[grain])
    )
    if len(span) < MIN_HISTORY:
        raise ForecastInputError(
            "insufficient_history",
            f"There are only {len(span)} {grain}s of history; a forecast needs at least "
            f"{MIN_HISTORY}.",
            fixable=False,
        )

    gaps = len(span) - len(series)
    if gaps > MAX_MISSING_SHARE * len(span):
        raise ForecastInputError(
            "too_sparse",
            f"{gaps} of the {len(span)} {grain}s in that history have no data. Group by a "
            f"longer period.",
            fixable=True,
        )

    series = series.reindex(span)
    # A total with no rows sold nothing; a level with no reading was still at some level.
    series = series.fillna(0.0) if kind == "total" else series.interpolate()

    return Series(
        periods=series.index,
        values=series.to_numpy(dtype=np.float64),
        grain=grain,
        kind=kind,
        filled=gaps,
        merged=merged,
        dropped_partial=dropped,
        capped=capped,
    )

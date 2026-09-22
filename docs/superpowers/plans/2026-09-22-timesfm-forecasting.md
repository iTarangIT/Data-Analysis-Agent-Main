# TimesFM Forecasting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Data Analysis Agent answer forecasting questions ("forecast revenue for the next six months") by calling a new `forecast_series` tool, backed by Google's TimesFM 2.5 running inside the FastAPI process. The tool is switched off by default.

**Architecture:**

- A new package `app/forecasting/` is the whole forecasting engine:
  - `preprocessing.py` turns rows into a clean series.
  - `engine.py` holds the `ForecastEngine` protocol and `TimesFMEngine`, the only code that touches `timesfm`/`torch`, which it imports lazily.
  - `service.py` holds the singleton `ForecastService`, its lock, and `load_forecaster`/`get_forecaster`.
- The agent gets a second `content_and_artifact` tool. It writes a period-aggregated SELECT, which passes through the existing guard. The rows are cleaned and forecast, and the result reaches the web client as the existing `chart` SSE event with `type: "forecast"`. The contract changes additively: no new event and no new stage.

**Tech Stack:**
- Backend: Python 3.12, FastAPI, langchain `create_agent`, pandas 3, numpy, `timesfm[torch]==2.0.2` (optional extra), pytest.
- Frontend: Next.js 16 / React / TypeScript, vitest; npm, not pnpm.

**Spec:** `docs/superpowers/specs/2026-09-22-timesfm-forecasting-design.md` (approved). Read it first; this plan argues from it.

## Global Constraints

**Layout and commands:**
- Repo root is `D:\itarang-agents`, and the branch is `feat/timesfm-forecasting`. The backend lives in `analyst-agent-backend/` and the frontend in `analyst-agent-frontend/`.
- Backend commands run from `analyst-agent-backend/` with the venv's Python: `.venv\Scripts\python -m pytest ...`, or `.venv/Scripts/python.exe` from Git Bash. The quick suite is `-m "not integration and not forecast"`.
- **Never run `pytest -m integration`** without first backing up the local `analyst` DB (`D:\postgres\bin\pg_dump.exe`). Its fixture deletes every row of the App DB. Nothing in this plan needs the integration suite.
- Frontend commands run from `analyst-agent-frontend/`: `npm test`, `npm run typecheck`, `npm run lint`.

**Model and switch:**
- The model is TimesFM **2.5**: checkpoint `google/timesfm-2.5-200m-pytorch`, package `timesfm[torch]==2.0.2`. Never TimesFM 3.x, whose weights are non-commercial and non-production only.
- `FORECAST_ENGINE` defaults to `"off"`. Production stays off: Render's free plan has 512 MB.

**Module boundaries:**
- `app/forecasting/preprocessing.py` and `engine.py` import nothing from `app`. `service.py` imports only `app.config` plus its sibling modules.
- Only `app/forecasting/engine.py` may import `timesfm` or `torch`, and only inside `TimesFMEngine.__init__`.

**Contracts:**
- The frozen stage list stays `router | sql_gen | sql_guard | db_exec | answer`.
- The SSE changes are additive only: `chart.type` gains `"forecast"` and `rejected.at` gains `"forecast"`. Backend and frontend change in the same PR.
- Prompts live only in `app/agent/prompts.py`. Changing one means live before/after eval pass rates (hard rule 6).

**Code style and colours:**
- Code style is `analyst-agent-backend/docs/CLAUDE.md` hard rules 1–4:
  - comments only for a non-obvious *why*;
  - no defensive code;
  - ruff line length 100;
  - type hints everywhere.
- Match the surrounding file's idioms.
- The UI uses existing `globals.css` tokens only (`series-1/2/3`, `line`, `line-strong`, `ink*`) and never a new colour.

**Commits:**
- Commit style is `feat(agent): …`, `feat(web): …`, `docs(status): …`.
- Every commit message ends with a blank line then `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- When `pyproject.toml` changes, regenerate `requirements.lock` with `pip-compile --extra dev -o requirements.lock pyproject.toml` and commit the two together (hard rule 11).

**Local machine:**
- Commit memory is tight. Before loading the real model, check `(Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory` (KB) is above about 3 GB.
- Start servers with `OPENBLAS_NUM_THREADS=1`, each in its own window: `Start-Process powershell -ArgumentList '-NoExit','-Command',...`.
- Put the Hugging Face cache on D: with `$env:HF_HOME="D:\hf-cache"`, because C: is full.

---

## File Structure

**Backend (`analyst-agent-backend/`), created:**

| File | Responsibility |
|---|---|
| `app/forecasting/__init__.py` | Package marker (empty) |
| `app/forecasting/preprocessing.py` | `prepare_series`, `Series`, `ForecastInputError`, `Grain`, `Kind`, `FREQ`, `label`, `MIN_HISTORY` |
| `app/forecasting/engine.py` | `EngineForecast`, `ForecastEngine` (Protocol), `TimesFMEngine` |
| `app/forecasting/service.py` | `ForecastService`, `Forecast`, `ForecastEngineError`, `load_forecaster`, `get_forecaster` |
| `tests/unit/test_forecast_preprocessing.py`, `test_forecast_service.py`, `test_forecast_startup.py`, `test_forecast_tool.py` | Unit tests |
| `tests/forecast/__init__.py`, `tests/forecast/test_timesfm_engine.py` | Real-model tests (marker `forecast`) |
| `evals/fixtures/monthly_revenue.csv`, `evals/golden_forecast.yaml` | Forecast eval fixture and suite |

**Backend, modified:**
- `app/config.py`, `pyproject.toml`, `requirements.lock`, `.env.example`
- `app/main.py`, `app/workers/runs.py`
- `app/agent/tools.py`, `app/agent/prompts.py`, `app/agent/graph.py`, `app/agent/middleware.py`
- `app/services/runs.py`, `app/services/charts.py`, `app/api/schemas.py`
- `evals/recorded.py`, `evals/golden_sql.yaml`
- Tests: `tests/unit/test_prompts.py`, `test_agent.py`, `test_middleware.py`, `test_charts.py`, `test_schemas.py`
- Docs: `docs/CLAUDE.md`, `docs/STATUS.md`, `docs/DEVELOPMENT.md`

**Frontend (`analyst-agent-frontend/`), modified:**
- `lib/api/types.ts`, `features/ask/run-types.ts`
- `features/ask/chart.ts` + `chart.test.ts`
- `features/ask/run-process.ts` + `run-process.test.ts`
- `components/ask/result-chart.tsx`, `components/ask/run-process.tsx`, `components/ask/ask-workspace.tsx`

---

### Task 1: Record the "before" eval numbers

Rule 6 needs a before/after pass rate for any prompt change. `golden_file` (6/7) and `golden_pdf` (4/4) were measured on the current prompts in `docs/STATUS.md` ("The 0.5 eval gate", commits `15bed9e`/`3ff76de`; nothing since has touched a prompt). So only `golden_sql` needs a run, and it has to happen **before Task 6 changes the prompts**.

**Files:** none changed; the numbers get written up in Task 11.

- [ ] **Step 1: Start the MCP server and the API on the current code (forecasting off by default)**

In PowerShell, from `analyst-agent-backend`:
```powershell
Start-Process powershell -ArgumentList '-NoExit','-Command','cd D:\itarang-agents\analyst-agent-backend; $env:OPENBLAS_NUM_THREADS="1"; .venv\Scripts\python -m uvicorn app.database_mcp:app --port 8001'
Start-Process powershell -ArgumentList '-NoExit','-Command','cd D:\itarang-agents\analyst-agent-backend; $env:OPENBLAS_NUM_THREADS="1"; $env:MAX_RUNS_PER_MINUTE="100"; .venv\Scripts\python -m uvicorn app.main:app --port 8000'
```
Expected: `curl http://127.0.0.1:8000/health` returns 200.

- [ ] **Step 2: Run the SQL suite live against the demo connection**

```powershell
$env:TOKEN = .venv\Scripts\python scripts/supabase_token.py it@itarang.com
$env:CONN = "<the demo Postgres connection id, from GET /connections>"
.venv\Scripts\python evals/run_evals.py --cases golden_sql.yaml
```
Expected: a pass count such as `5/6`. Write down the number and the failing questions for Task 11.

If no demo connection exists or the Gemini quota is exhausted, don't try to work around it. Record "golden_sql before: not measured (reason)", and Task 11 reports it that way.

---

### Task 2: Preprocessing — rows to a clean, evenly spaced series

**Files:**
- Create: `analyst-agent-backend/app/forecasting/__init__.py` (empty)
- Create: `analyst-agent-backend/app/forecasting/preprocessing.py`
- Test: `analyst-agent-backend/tests/unit/test_forecast_preprocessing.py`

**Interfaces:**
- Produces:
  - `Grain = Literal["hour","day","week","month","quarter","year"]`
  - `Kind = Literal["total","level"]`
  - `FREQ: dict[str, str]`
  - `MIN_HISTORY = 8`, `MAX_MISSING_SHARE = 0.3`
  - `class ForecastInputError(Exception)` with `.code: str`, `.message: str`, `.fixable: bool`
  - `@dataclass(frozen=True) class Series` with fields `periods: pd.PeriodIndex`, `values: np.ndarray`, `grain: Grain`, `kind: Kind`, `filled: int`, `merged: int`, `dropped_partial: str | None`, `capped: bool`, and `__len__`
  - `label(period: pd.Period) -> str`
  - `prepare_series(columns: list[str], rows: list, time_column: str, value_column: str, grain: Grain, kind: Kind, today: date, capped: bool = False) -> Series`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_forecast_preprocessing.py`:
```python
"""Rows into a series. No model involved, so every rule here is assertable offline."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.forecasting.preprocessing import (
    MIN_HISTORY,
    ForecastInputError,
    label,
    prepare_series,
)

TODAY = date(2026, 9, 22)
COLUMNS = ["month", "revenue"]


def months(n: int, end_month: int = 8, value=lambda i: 100 + i) -> list[list]:
    """`n` month-start dates ending at 2026-`end_month`, oldest first."""
    rows = []
    for i in range(n):
        back = n - 1 - i
        year, month = 2026 + (end_month - 1 - back) // 12, (end_month - 1 - back) % 12 + 1
        rows.append([date(year, month, 1), value(i)])
    return rows


def prepare(rows, grain="month", kind="total", columns=COLUMNS, **kwargs):
    return prepare_series(columns, rows, "month", "revenue", grain, kind, TODAY, **kwargs)


def error(rows, **kwargs) -> ForecastInputError:
    with pytest.raises(ForecastInputError) as caught:
        prepare(rows, **kwargs)
    return caught.value


class TestShapes:
    def test_date_objects_become_one_value_per_month_oldest_first(self):
        series = prepare(months(12)[::-1])

        assert [label(p) for p in series.periods][:2] == ["2025-09", "2025-10"]
        assert label(series.periods[-1]) == "2026-08"
        assert series.values.tolist() == [float(100 + i) for i in range(12)]

    def test_iso_strings_across_a_dst_change_keep_their_wall_clock_month(self):
        # Postgres timestamptz arrives through MCP JSON as strings with the session's offset,
        # which changes at DST. Converting to UTC would move April's midnight into March.
        rows = [[f"2026-{m:02d}-01T00:00:00{'+01:00' if m < 4 else '+02:00'}", m] for m in range(1, 9)]
        rows = [[f"2025-{m:02d}-01T00:00:00+01:00", m] for m in range(9, 13)] + rows

        series = prepare(rows)

        assert "2026-04" in [label(p) for p in series.periods]
        assert len(series) == 12

    def test_decimals_and_numeric_strings_are_numbers(self):
        rows = [[r[0], Decimal("10.50") if i % 2 else "7.25"] for i, r in enumerate(months(8))]

        assert prepare(rows).values.tolist()[:2] == [7.25, 10.5]

    def test_a_datetime_is_accepted_as_well_as_a_date(self):
        rows = [[datetime(r[0].year, r[0].month, 1, 9, 30), r[1]] for r in months(8)]

        assert len(prepare(rows)) == 8


class TestDuplicatesAndGaps:
    def test_a_total_adds_up_duplicate_periods(self):
        rows = [*months(8), [date(2026, 8, 15), 50]]

        series = prepare(rows, kind="total")

        assert series.values[-1] == 107 + 50
        assert series.merged == 1

    def test_a_level_averages_duplicate_periods(self):
        rows = [*months(8), [date(2026, 8, 15), 7]]

        assert prepare(rows, kind="level").values[-1] == (107 + 7) / 2

    def test_a_missing_month_of_a_total_is_zero(self):
        rows = [r for i, r in enumerate(months(10)) if i != 4]

        series = prepare(rows, kind="total")

        assert series.values[4] == 0.0
        assert series.filled == 1

    def test_a_missing_month_of_a_level_is_interpolated(self):
        rows = [r for i, r in enumerate(months(10)) if i != 4]

        assert prepare(rows, kind="level").values[4] == 104.0

    def test_a_null_value_is_a_gap_not_a_zero_or_a_crash(self):
        rows = months(10)
        rows[4][1] = None

        series = prepare(rows, kind="level")

        assert series.values[4] == 104.0
        assert not any(v != v for v in series.values), "NaN reached the series"

    def test_the_month_still_in_progress_is_dropped(self):
        series = prepare(months(12, end_month=9))

        assert label(series.periods[-1]) == "2026-08"
        assert series.dropped_partial == "2026-09"


class TestWeeks:
    def test_weeks_start_on_monday_like_date_trunc(self):
        rows = [[date(2026, 6, 1) + timedelta(weeks=i), 1] for i in range(9)]  # nine Mondays
        rows.append([date(2026, 7, 8), 1])  # a Wednesday inside the week of 2026-07-06

        series = prepare(rows, grain="week")

        assert label(series.periods[0]) == "2026-06-01"
        assert series.merged == 1


class TestRefusals:
    def test_a_missing_column_is_fixable_and_names_what_exists(self):
        e = error(months(8), columns=["period", "revenue"])

        assert (e.code, e.fixable) == ("missing_column", True)
        assert "period" in e.message

    def test_no_rows_cannot_be_forecast(self):
        assert (error([]).code, error([]).fixable) == ("empty", False)

    def test_text_in_the_time_column_is_fixable(self):
        e = error([["soon", 1]] * 8)

        assert (e.code, e.fixable) == ("bad_timestamps", True)

    def test_text_in_the_value_column_is_fixable_and_quoted(self):
        rows = months(8)
        rows[3][1] = "n/a"

        e = error(rows)

        assert (e.code, e.fixable) == ("not_numeric", True)
        assert "n/a" in e.message

    def test_too_little_history_cannot_be_forecast(self):
        e = error(months(MIN_HISTORY - 1))

        assert (e.code, e.fixable) == ("insufficient_history", False)

    def test_mostly_empty_periods_ask_for_a_longer_grain(self):
        rows = [r for i, r in enumerate(months(12)) if i % 2 == 0 or i == 11]

        e = error(rows)

        assert (e.code, e.fixable) == ("too_sparse", True)

    def test_a_capped_result_oldest_first_is_fixable(self):
        e = error(months(12), capped=True)

        assert (e.code, e.fixable) == ("wrong_order", True)

    def test_a_capped_result_newest_first_is_used(self):
        series = prepare(months(12)[::-1], capped=True)

        assert series.capped and len(series) == 12
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/unit/test_forecast_preprocessing.py -q --no-cov`
Expected: collection error, `ModuleNotFoundError: No module named 'app.forecasting'`.

- [ ] **Step 3: Write the implementation**

`app/forecasting/__init__.py`: an empty file.

`app/forecasting/preprocessing.py`:
```python
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
    # A week prints as its whole range; its Monday is what the SQL grouped on.
    return period.start_time.date().isoformat() if period.freqstr.startswith("W") else str(period)


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/unit/test_forecast_preprocessing.py -q --no-cov`
Expected: all pass. If pandas 3 rejects a frequency alias (`M`, `Q`, `Y` for periods), switch it to the alias the error message names and rerun. Change `FREQ` only.

- [ ] **Step 5: Lint and commit**

```bash
cd analyst-agent-backend && .venv/Scripts/python.exe -m ruff format app/forecasting tests/unit/test_forecast_preprocessing.py && .venv/Scripts/python.exe -m ruff check app/forecasting tests/unit/test_forecast_preprocessing.py
git add app/forecasting/__init__.py app/forecasting/preprocessing.py tests/unit/test_forecast_preprocessing.py
git commit -m "feat(agent): turn query rows into a clean series for forecasting" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The engine interface and the forecasting service (with settings)

**Files:**
- Create: `analyst-agent-backend/app/forecasting/engine.py`
- Create: `analyst-agent-backend/app/forecasting/service.py`
- Modify: `analyst-agent-backend/app/config.py` (after `max_tool_calls`, around line 88)
- Modify: `analyst-agent-backend/.env.example`
- Modify: `analyst-agent-backend/pyproject.toml` and `requirements.lock` (add `numpy` as a direct dependency)
- Test: `analyst-agent-backend/tests/unit/test_forecast_service.py`

**Interfaces:**
- Consumes (Task 2): `Series`, `ForecastInputError`, `label`
- Produces:
  - `@dataclass(frozen=True) class EngineForecast(mean: np.ndarray, lower: np.ndarray, upper: np.ndarray)`
  - `class ForecastEngine(Protocol)` with `name: str`, `max_context: int`, `max_horizon: int` and `predict(values: np.ndarray, horizon: int) -> EngineForecast`
  - `class TimesFMEngine` with `__init__(checkpoint: str, threads: int)`. It is written here but exercised only in Task 4.
  - `class ForecastEngineError(Exception)`
  - `@dataclass(frozen=True) class Forecast` with fields `history: Series`, `periods: list[str]`, `mean: list[float]`, `lower: list[float]`, `upper: list[float]`, `model: str`, and methods `summary() -> dict`, `chart_payload() -> dict`
  - `INTERVAL = 0.8`
  - `class ForecastService` with `__init__(engine: ForecastEngine)` and `forecast(series: Series, horizon: int) -> Forecast`
  - `load_forecaster() -> None` and `get_forecaster() -> ForecastService | None`
  - Settings: `forecast_engine: Literal["off","timesfm"]`, `forecast_checkpoint: str`, `forecast_threads: int`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_forecast_service.py`:
```python
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
            service, "TimesFMEngine", lambda checkpoint, threads: built.append(1) or RecordingEngine()
        )

        service.load_forecaster()
        service.load_forecaster()

        assert len(built) == 1
        assert isinstance(service.get_forecaster(), ForecastService)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/unit/test_forecast_service.py -q --no-cov`
Expected: `ModuleNotFoundError: No module named 'app.forecasting.engine'`.

- [ ] **Step 3: Add the settings**

In `app/config.py`, directly after `max_tool_calls: int = 6`:
```python

    # Forecasting runs a ~200M-parameter model in this process, about a gigabyte resident, which
    # Render's free plan cannot hold. Off, the forecast tool is not offered and nothing loads.
    forecast_engine: Literal["off", "timesfm"] = "off"
    forecast_checkpoint: str = "google/timesfm-2.5-200m-pytorch"
    forecast_threads: int = 2
```

Append to `.env.example`:
```
# Forecasting. Off by default; "timesfm" needs `pip install -e ".[forecast]"` and ~1.5 GB of RAM.
FORECAST_ENGINE=off
# FORECAST_CHECKPOINT=google/timesfm-2.5-200m-pytorch
# FORECAST_THREADS=2
```

- [ ] **Step 4: Write the engine module**

`app/forecasting/engine.py`:
```python
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
        return EngineForecast(
            mean=point[0], lower=quantiles[0, :, P10], upper=quantiles[0, :, P90]
        )
```

- [ ] **Step 5: Write the service module**

`app/forecasting/service.py`:
```python
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
                for p, m, lo, hi in zip(self.periods, self.mean, self.lower, self.upper, strict=True)
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
                for p, m, lo, hi in zip(self.periods, self.mean, self.lower, self.upper, strict=True)
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
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/unit/test_forecast_service.py tests/unit/test_forecast_preprocessing.py -q --no-cov`
Expected: all pass.

- [ ] **Step 7: Make numpy a direct dependency and regenerate the lock**

In `pyproject.toml` `dependencies`, after `"pandas>=2.2",` add:
```toml
    # Imported directly by app/forecasting, not only through pandas.
    "numpy>=2",
```
Run: `.venv\Scripts\python -m piptools compile --extra dev -o requirements.lock pyproject.toml`
Expected: the diff to `requirements.lock` is limited to numpy's `# via` lines. Check with `git diff --stat requirements.lock`. Any version change is a sign pip-compile upgraded something; revert it and retry with the same pins.

- [ ] **Step 8: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff format app tests && .venv/Scripts/python.exe -m ruff check app tests
git add app/forecasting/engine.py app/forecasting/service.py app/config.py .env.example pyproject.toml requirements.lock tests/unit/test_forecast_service.py
git commit -m "feat(agent): a forecasting service behind a replaceable engine" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: TimesFM for real — the optional extra and the model test

**Files:**
- Modify: `analyst-agent-backend/pyproject.toml` (an optional extra and a pytest marker)
- Modify: `analyst-agent-backend/requirements.lock` (regenerated; the extra stays out)
- Create: `analyst-agent-backend/tests/forecast/__init__.py` (empty)
- Create: `analyst-agent-backend/tests/forecast/test_timesfm_engine.py`

**Interfaces:**
- Consumes (Task 3): `TimesFMEngine(checkpoint, threads)`, `.predict(values, horizon) -> EngineForecast`

- [ ] **Step 1: Add the extra and the marker**

In `pyproject.toml` under `[project.optional-dependencies]`, after the `dev = [...]` list:
```toml
# Off by default and never installed on Render's free plan: torch and the checkpoint need about
# 1.5 GB. TimesFM 2.5 because its weights are Apache-2.0; 3.x weights are non-commercial only.
forecast = ["timesfm[torch]==2.0.2"]
```
In `[tool.pytest.ini_options]` `markers`, add:
```toml
    "forecast: loads the real TimesFM checkpoint (pip install -e .[forecast])",
```
Regenerate the lock (`--extra dev` only, so torch stays out): `.venv\Scripts\python -m piptools compile --extra dev -o requirements.lock pyproject.toml`. Expected: `git diff requirements.lock` is empty, or only the header changes.

- [ ] **Step 2: Write the model test**

`tests/forecast/test_timesfm_engine.py`:
```python
"""The real checkpoint. Slow and about a gigabyte, so it runs only under `-m forecast`."""

import numpy as np
import pytest

pytest.importorskip("timesfm")

from app.forecasting.engine import TimesFMEngine  # noqa: E402

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
```

- [ ] **Step 3: Check the machine can hold the model, then install the extra**

```powershell
[math]::Round((Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory / 1MB, 1)   # GB free commit; need > 3
$env:HF_HOME = "D:\hf-cache"
.venv\Scripts\python -m pip install -e ".[forecast]"
```
Expected: `timesfm-2.0.2` and a CPU `torch` are installed. On Windows, the PyPI torch wheel is CPU-only.

- [ ] **Step 4: Run the model tests and measure**

```powershell
$env:HF_HOME = "D:\hf-cache"; $env:OPENBLAS_NUM_THREADS = "1"
.venv\Scripts\python -m pytest -m forecast tests/forecast -q --no-cov
```
Expected: 2 passed. The first run downloads the checkpoint (about 0.9 GB) to `D:\hf-cache`.

If `from_pretrained` rejects `torch_compile=False`, remove that keyword; 2.0.2's default is no compile. Then rerun.

If `lower <= mean` fails, print `out` and check the quantile indices against `timesfm`'s docstring for `forecast` before changing `P10`/`P90`.

Then measure load time, resident memory and latency for the STATUS write-up:
```powershell
.venv\Scripts\python -c "import os, time, numpy as np; t=time.time(); from app.forecasting.engine import TimesFMEngine; e=TimesFMEngine('google/timesfm-2.5-200m-pytorch', 2); print('load_s', round(time.time()-t,1)); t=time.time(); e.predict(np.arange(36.0), 6); print('predict_ms', round((time.time()-t)*1000)); print('pid', os.getpid()); input('measure RSS now, then Enter')"
```
While it waits, run `(Get-Process -Id <pid>).WorkingSet64 / 1MB` in another window. Record load seconds, prediction milliseconds and RSS in MB.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements.lock tests/forecast/__init__.py tests/forecast/test_timesfm_engine.py
git commit -m "feat(agent): TimesFM 2.5 as an optional extra, with a real-model test" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Load the model once at startup

**Files:**
- Modify: `analyst-agent-backend/app/main.py` (the `lifespan` function, lines 25-47)
- Modify: `analyst-agent-backend/app/workers/runs.py` (`_startup`, lines 105-112)
- Test: `analyst-agent-backend/tests/unit/test_forecast_startup.py`

**Interfaces:**
- Consumes (Task 3): `load_forecaster()`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_forecast_startup.py`:
```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/unit/test_forecast_startup.py -q --no-cov`
Expected: FAIL with `AttributeError: <module 'app.main'> does not have the attribute 'load_forecaster'`.

- [ ] **Step 3: Wire the API lifespan**

In `app/main.py` add `import asyncio` at the top, and `from app.forecasting.service import load_forecaster` among the `app.` imports (sorted after `app.db.session`). In `lifespan`, after the `probe_mcp()` block and before `setup_store()`:
```python
    if s.forecast_engine != "off" and not s.queue_enabled:
        # Off the event loop: loading the checkpoint takes seconds. A model that will not load
        # fails the boot, for the same reason a missing MCP server does. In queue mode the
        # worker runs every tool, so the API would hold a gigabyte it never uses.
        await asyncio.to_thread(load_forecaster)
```

- [ ] **Step 4: Wire the worker**

In `app/workers/runs.py` (which already imports `asyncio`), add `from app.forecasting.service import load_forecaster` after `from app.db.session import SessionLocal`. In `_startup`, after the `probe_mcp()` block:
```python
    if get_settings().forecast_engine != "off":
        await asyncio.to_thread(load_forecaster)
```

- [ ] **Step 5: Run the tests to verify they pass, plus the tracing tests that share `_startup`**

Run: `.venv\Scripts\python -m pytest tests/unit/test_forecast_startup.py tests/unit/test_tracing.py -q --no-cov`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/workers/runs.py tests/unit/test_forecast_startup.py
git commit -m "feat(agent): load the forecasting model once at startup" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The `forecast_series` tool, its prompts and its registration

This task holds the tool, its descriptions and its registration in `build_agent`. A reviewer judges these together: the tool's text is its prompt, and it is offered only when the prompt describes it.

**Files:**
- Modify: `analyst-agent-backend/app/agent/prompts.py` (append the forecast constants and `capability()`)
- Modify: `analyst-agent-backend/app/agent/tools.py` (shared select helper, `make_forecast_tool`, `make_tools`)
- Modify: `analyst-agent-backend/app/agent/graph.py` (`build_agent`)
- Modify: `analyst-agent-backend/evals/recorded.py` (`prompt_sha`)
- Test: `analyst-agent-backend/tests/unit/test_forecast_tool.py` (new), `tests/unit/test_prompts.py`, `tests/unit/test_agent.py`

**Interfaces:**
- Consumes:
  - Task 2: `prepare_series`, `ForecastInputError`, `Grain`, `Kind`
  - Task 3: `ForecastService`, `ForecastEngineError`, `get_forecaster`, `EngineForecast`
- Produces:
  - `FORECAST_TOOL_NAME = "forecast_series"`
  - `make_forecast_tool(connector, catalog, forecaster: ForecastService, today: date) -> BaseTool`
  - `make_tools(connector, catalog, with_memory, forecaster: ForecastService | None = None, today: date | None = None)`
  - `capability(forecasting: bool) -> str`, `FORECAST_CAPABILITY`, `FORECAST_OFF`
  - Success artifact keys: `sql, columns, rows, truncated, ms, what, why, forecast`. `forecast` is `Forecast.chart_payload()` plus `time_column` and `value_column`.
  - Error artifact: `{"error": str, "at": "forecast", "sql", "what", "why"}`
  - Content on error: `{"error": {"code", "message", "fixable"}}`
  - Content on success: `{"forecast": Forecast.summary()}`

- [ ] **Step 1: Write the failing tool tests**

`tests/unit/test_forecast_tool.py`:
```python
"""The forecast tool: the query tool's guard, then the forecasting service, as one call."""

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
from langchain.tools import ToolRuntime

from app.agent.context import RunContext
from app.agent.tools import FORECAST_TOOL_NAME, make_forecast_tool, make_tools
from app.catalog.types import Catalog, CatalogTable, Column, TableDef
from app.config import get_settings
from app.forecasting.engine import EngineForecast
from app.forecasting.service import ForecastService

CONTEXT = RunContext(tenant_id="t_test", connection_id="c1", run_id="r1", thread_id="th1")
TODAY = date(2026, 9, 22)
CATALOG = Catalog(
    tables=[
        CatalogTable(
            definition=TableDef(
                name="sales",
                columns=[Column(name="month", type="date"), Column(name="revenue", type="numeric")],
            )
        )
    ]
)


class FlatEngine:
    """Forecasts the last value, with a range of one either side."""

    name = "flat"
    max_context = 1024
    max_horizon = 256

    def predict(self, values, horizon):
        mean = np.full(horizon, values[-1])
        return EngineForecast(mean=mean, lower=mean - 1, upper=mean + 1)


class FakeConnector:
    kind = "postgres"
    dialect = "postgres"

    def __init__(self, rows):
        self.rows = rows
        self.executed: list[str] = []

    def run_select(self, sql, max_rows):
        self.executed.append(sql)
        return ["month", "revenue"], self.rows[:max_rows]


def months(n: int, newest_first: bool = True) -> list[tuple]:
    periods = pd.period_range(end="2026-08", periods=n, freq="M")
    rows = [(p.start_time.date().isoformat(), 100 + i) for i, p in enumerate(periods)]
    return rows[::-1] if newest_first else rows


def call(rows, **args):
    tool = make_forecast_tool(FakeConnector(rows), CATALOG, ForecastService(FlatEngine()), TODAY)
    base = {
        "sql": "select month, revenue from sales order by month desc",
        "time_column": "month",
        "value_column": "revenue",
        "grain": "month",
        "horizon": 3,
        "kind": "total",
        "what": "Totalled revenue by month.",
        "why": "You asked for a forecast.",
    }
    runtime = ToolRuntime(
        state={}, context=CONTEXT, config={}, stream_writer=lambda _: None,
        tool_call_id="c1", store=None,
    )  # fmt: skip
    msg = tool.invoke(
        {"name": tool.name, "args": {**base, **args, "runtime": runtime}, "id": "c1", "type": "tool_call"}
    )
    return json.loads(msg.content) if msg.content.startswith("{") else msg.content, msg.artifact


class TestContract:
    def test_the_model_must_give_everything_but_the_explanation(self):
        tool = make_forecast_tool(FakeConnector([]), CATALOG, ForecastService(FlatEngine()), TODAY)

        assert tool.name == FORECAST_TOOL_NAME
        assert sorted(tool.tool_call_schema.model_json_schema()["required"]) == [
            "grain", "horizon", "kind", "sql", "time_column", "value_column",
        ]  # fmt: skip

    def test_it_is_offered_only_when_a_model_is_loaded(self):
        connector = FakeConnector([])

        without = make_tools(connector, CATALOG, with_memory=False)
        with_model = make_tools(
            connector, CATALOG, with_memory=False,
            forecaster=ForecastService(FlatEngine()), today=TODAY,
        )  # fmt: skip

        assert [t.name for t in without] == ["query_database"]
        assert [t.name for t in with_model] == ["query_database", FORECAST_TOOL_NAME]


class TestAForecast:
    def test_the_model_is_told_the_forecast(self):
        content, _ = call(months(12))

        forecast = content["forecast"]
        assert [p["period"] for p in forecast["points"]] == ["2026-09", "2026-10", "2026-11"]
        assert forecast["points"][0] == {"period": "2026-09", "forecast": 111.0, "low": 110.0, "high": 112.0}
        assert forecast["history"]["to"] == "2026-08" and forecast["history"]["periods"] == 12

    def test_the_artifact_carries_what_the_stream_needs(self):
        _, artifact = call(months(12))

        assert artifact["sql"].upper().startswith("SELECT") and "LIMIT" in artifact["sql"].upper()
        assert (artifact["what"], artifact["why"]) == (
            "Totalled revenue by month.", "You asked for a forecast.",
        )  # fmt: skip
        assert artifact["columns"] == ["month", "revenue"] and len(artifact["rows"]) == 12
        assert artifact["forecast"]["time_column"] == "month"
        assert artifact["forecast"]["value_column"] == "revenue"
        assert artifact["forecast"]["points"][0] == ["2026-09", 111.0, 110.0, 112.0]


class TestRefusals:
    def test_the_guard_refuses_exactly_as_it_does_for_the_query_tool(self):
        content, artifact = call(months(12), sql="delete from sales")

        assert content.startswith("Query rejected:")
        assert artifact["at"] == "guard"

    def test_history_the_data_cannot_support_is_explained_not_retried(self):
        content, artifact = call(months(5))

        assert content["error"]["code"] == "insufficient_history"
        assert content["error"]["fixable"] is False
        assert artifact["at"] == "forecast" and artifact["error"]

    def test_too_far_ahead_is_explained_not_retried(self):
        content, _ = call(months(12), horizon=24)

        assert content["error"] == {
            "code": "horizon_too_long",
            "message": content["error"]["message"],
            "fixable": False,
        }


class TestTheRowCap:
    @pytest.fixture(autouse=True)
    def small_cap(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "max_rows", 12)

    def test_newest_first_the_latest_periods_are_used(self):
        content, artifact = call(months(20))

        assert content["forecast"]["history"]["capped"] is True
        assert content["forecast"]["history"]["to"] == "2026-08"
        assert artifact["truncated"] is True and len(artifact["rows"]) == 12

    def test_oldest_first_the_model_is_asked_to_reorder(self):
        content, artifact = call(months(20, newest_first=False))

        assert content["error"]["code"] == "wrong_order"
        assert content["error"]["fixable"] is True
        assert artifact["at"] == "forecast"
```

- [ ] **Step 2: Write the failing prompt and agent tests**

Append to `tests/unit/test_prompts.py` (and add `FORECAST_CAPABILITY, FORECAST_OFF, capability` to its import from `app.agent.prompts`):
```python
class TestForecastingBlock:
    def test_the_sql_rules_come_first_either_way(self):
        assert capability(True).startswith(SQL_CAPABILITY)
        assert capability(False).startswith(SQL_CAPABILITY)

    def test_with_a_model_loaded_the_forecast_tool_is_explained(self):
        assert FORECAST_CAPABILITY in capability(True)
        assert FORECAST_OFF not in capability(True)

    def test_without_one_forecasting_is_declared_unavailable(self):
        assert FORECAST_OFF in capability(False)
        assert "do not work out a projection yourself" in FORECAST_OFF

    def test_forecast_figures_are_tool_output_but_never_hand_extrapolated(self):
        # AGENT_SYSTEM allows only figures a tool returned; a forecast's points are exactly that.
        assert "figures a tool returned" in FORECAST_CAPABILITY
        assert "Never extrapolate a figure yourself" in FORECAST_CAPABILITY
```

Append to `tests/unit/test_agent.py`. Add `FORECAST_CAPABILITY, FORECAST_OFF` from `app.agent.prompts`, `ForecastService` from `app.forecasting.service` and `EngineForecast` from `app.forecasting.engine` to its imports, plus `import numpy as np`:
```python
class FlatEngine:
    name = "flat"
    max_context = 1024
    max_horizon = 256

    def predict(self, values, horizon):
        mean = np.full(horizon, values[-1])
        return EngineForecast(mean=mean, lower=mean - 1, upper=mean + 1)


def _built_with(forecaster):
    with (
        patch("app.agent.graph.get_forecaster", return_value=forecaster),
        patch("app.agent.graph.create_agent") as create,
        patch("app.agent.graph.get_llm"),
    ):
        build_agent(FakeConnector(), CATALOG, middleware=[])
    kwargs = create.call_args.kwargs
    return kwargs["system_prompt"], [t.name for t in kwargs["tools"]]


class TestForecastingIsOfferedOnlyWhenLoaded:
    def test_off_the_prompt_says_so_and_no_tool_is_offered(self):
        prompt, tools = _built_with(None)

        assert FORECAST_OFF in prompt
        assert tools == ["query_database"]

    def test_on_the_prompt_explains_the_tool_that_is_offered(self):
        prompt, tools = _built_with(ForecastService(FlatEngine()))

        assert FORECAST_CAPABILITY in prompt
        assert "forecast_series" in tools
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/unit/test_forecast_tool.py tests/unit/test_prompts.py tests/unit/test_agent.py -q --no-cov`
Expected: `ImportError: cannot import name 'FORECAST_TOOL_NAME'` and `cannot import name 'FORECAST_CAPABILITY'`.

- [ ] **Step 4: Add the prompts**

Append to `app/agent/prompts.py`:
```python


FORECAST_CAPABILITY = """Forecasting:
- A question about the future - forecast, predict, estimate, project, expect, next week, next
  month, next quarter, next year, tomorrow - goes to the forecast tool, never the query tool.
  Anything the data already holds stays with the query tool.
- Call the forecast tool on its own, never alongside another tool call in the same turn.
- Its SQL returns one row per period: the period's start, cast to a date, and the measure,
  grouped to the grain the question asks about and ordered newest first. Leave a period with
  no rows out rather than inventing it; the tool fills the gap.
- kind is total for sums and counts (sales, revenue, units, visits, consumption) and level for
  readings (price, balance, stock on hand, temperature).
- horizon counts periods of that grain: the next six months is 6 at month grain, tomorrow is 1
  at day grain, the next quarter is 3 at month grain.
- The forecast's points are figures a tool returned, so state them, always as a forecast: the
  next period's figure, the total or end point over the horizon, and the range, and how much
  history it rests on and when that history ends. Do not list every period; the forecast
  table shows them. Never extrapolate a figure yourself.
- If the forecast tool says it cannot forecast and that is not fixable, tell the person why in
  plain words and do not try again."""

FORECAST_OFF = """Forecasting:
- Forecasting is not available on this service. When asked to predict a future figure, say so
  in one sentence, do not work out a projection yourself, and offer the history that bears on
  it."""


def capability(forecasting: bool) -> str:
    """The capability block: SQL always, and forecasting only when a model is loaded. The one
    place it is composed, so the agent and the eval cassette hash cannot disagree."""
    return f"{SQL_CAPABILITY}\n\n{FORECAST_CAPABILITY if forecasting else FORECAST_OFF}"


FORECAST_TOOL_DESC = """Forecast a measure forward in time from its history in the customer's
database. Give one read-only SQL SELECT returning that history, one row per period, and say
which column is the period, which is the measure, the grain, how many periods ahead, and
whether the measure is a total or a level. The tool cleans the series, fills gaps and returns
a forecast for each future period with an 80% range.

Use only the tables and columns described for the query tool. Use this only for questions
about the future; historic questions belong to the query tool."""

FORECAST_SQL_ARG = """One {dialect} SELECT returning the history: the period's start cast to a
date, and the measure, one row per period, ordered by the period newest first. No prose, no
code fences."""

FORECAST_TIME_ARG = "The result column holding the period's start."

FORECAST_VALUE_ARG = "The result column holding the measure to forecast."

FORECAST_GRAIN_ARG = """The period each row covers, matching how the SQL groups: hour, day,
week, month, quarter or year."""

FORECAST_HORIZON_ARG = "How many periods of that grain to forecast ahead."

FORECAST_KIND_ARG = """total when the measure adds up over a period (sales, revenue, units,
visits); level when it is a reading at a point in time (price, balance, stock on hand,
temperature)."""
```

- [ ] **Step 5: Add the tool**

In `app/agent/tools.py`:

(a) Update the imports:
```python
import json
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, create_model

from app.agent import memory
from app.agent.context import RunContext
from app.agent.nodes.sql_guard import validate_sql
from app.agent.prompts import (
    DIALECTS,
    FORECAST_GRAIN_ARG,
    FORECAST_HORIZON_ARG,
    FORECAST_KIND_ARG,
    FORECAST_SQL_ARG,
    FORECAST_TIME_ARG,
    FORECAST_TOOL_DESC,
    FORECAST_VALUE_ARG,
    QUERY_TOOL_DESC,
    QUERY_TOOL_SQL_ARG,
    QUERY_TOOL_WHAT_ARG,
    QUERY_TOOL_WHY_ARG,
    REMEMBER_DEFINITION_ARG,
    REMEMBER_TERM_ARG,
    REMEMBER_TOOL_DESC,
)
from app.agent.schema_context import render_relationships, render_tables
from app.catalog.types import Catalog
from app.config import get_settings
from app.connectors.base import SqlConnector
from app.forecasting.preprocessing import ForecastInputError, Grain, Kind, prepare_series
from app.forecasting.service import ForecastEngineError, ForecastService

TOOL_NAME = "query_database"
FORECAST_TOOL_NAME = "forecast_series"
REMEMBER_TOOL_NAME = "remember"
```

(b) Below `RememberArgs`, add the shared select:
```python
@dataclass(frozen=True)
class _Selected:
    sql: str
    columns: list[str]
    rows: list
    ms: int


@dataclass(frozen=True)
class _Refused:
    content: str
    artifact: dict[str, Any]


def _select(
    connector: SqlConnector,
    allowed: set[str],
    sql: str,
    cap: int,
    runtime: ToolRuntime[RunContext],
    explained: dict[str, str],
) -> _Selected | _Refused:
    """Guard, then run, fetching one row past `cap` so the caller can tell it was truncated.

    Shared by both tools, so a refusal reads the same to the model whichever tool it called.
    """
    safe_sql, err = validate_sql(sql, allowed, cap, connector.dialect)
    if err:
        # The artifact carries the rejected SQL so a later success can be recorded against it
        # as a correction.
        return _Refused(
            f"Query rejected: {err}.{_prior_fix(runtime, sql)} Rewrite it.",
            {"error": err, "at": "guard", "sql": sql, **explained},
        )

    t0 = time.perf_counter()
    try:
        cols, rows = connector.run_select(safe_sql, cap + 1)
    except Exception as e:
        message = f"database error: {e}"
        return _Refused(
            f"Query failed: {message}. Rewrite it.",
            {"error": message, "at": "database", "sql": sql, **explained},
        )
    return _Selected(safe_sql, cols, rows, int((time.perf_counter() - t0) * 1000))
```
`allowed` is `catalog.table_names`, a `set[str]` (`app/catalog/types.py:57`).

(c) Replace the body of `query_database` (everything after `explained = {...}`) with:
```python
        got = _select(connector, allowed, sql, max_rows, runtime, explained)
        if isinstance(got, _Refused):
            return got.content, got.artifact

        capped = [list(r) for r in got.rows[:max_rows]]
        result = {
            "sql": got.sql,
            "columns": got.columns,
            "rows": capped,
            "truncated": len(got.rows) > max_rows,
            "ms": got.ms,
            **explained,
        }
        preview = json.dumps(
            {"columns": got.columns, "rows": capped[:PREVIEW_ROWS], "row_count": len(capped)},
            default=str,
        )
        return preview, result
```

(d) After `make_query_tool`, add:
```python
def make_forecast_tool(
    connector: SqlConnector, catalog: Catalog, forecaster: ForecastService, today: date
) -> BaseTool:
    allowed = catalog.table_names
    args = create_model(
        "ForecastSeriesArgs",
        sql=(str, Field(description=FORECAST_SQL_ARG.format(dialect=DIALECTS[connector.dialect]))),
        time_column=(str, Field(description=FORECAST_TIME_ARG)),
        value_column=(str, Field(description=FORECAST_VALUE_ARG)),
        grain=(Grain, Field(description=FORECAST_GRAIN_ARG)),
        # No upper bound here: the service knows how far this history can reach and says so
        # in words the model can pass on, which a schema error would not.
        horizon=(int, Field(ge=1, description=FORECAST_HORIZON_ARG)),
        kind=(Kind, Field(description=FORECAST_KIND_ARG)),
        what=(str, Field(default="", description=QUERY_TOOL_WHAT_ARG)),
        why=(str, Field(default="", description=QUERY_TOOL_WHY_ARG)),
    )

    @tool(
        FORECAST_TOOL_NAME,
        description=FORECAST_TOOL_DESC,
        args_schema=args,
        response_format="content_and_artifact",
    )
    def forecast_series(
        sql: str,
        time_column: str,
        value_column: str,
        grain: Grain,
        horizon: int,
        kind: Kind,
        runtime: ToolRuntime[RunContext],
        what: str = "",
        why: str = "",
    ) -> tuple[str, dict[str, Any]]:
        # The same cap as the query tool, because the MCP server applies its own `max_rows` to
        # every Postgres query regardless of what the caller asks for.
        max_rows = get_settings().max_rows
        explained = {"what": what, "why": why}

        got = _select(connector, allowed, sql, max_rows, runtime, explained)
        if isinstance(got, _Refused):
            return got.content, got.artifact

        rows = got.rows[:max_rows]
        capped = len(got.rows) > max_rows
        try:
            series = prepare_series(
                got.columns, rows, time_column, value_column, grain, kind, today, capped
            )
            forecast = forecaster.forecast(series, horizon)
        except ForecastInputError as e:
            return _cannot_forecast(e.code, e.message, e.fixable, got.sql, explained)
        except ForecastEngineError as e:
            return _cannot_forecast(
                "model_failed", f"the forecasting model failed: {e}", False, got.sql, explained
            )

        result = {
            "sql": got.sql,
            "columns": got.columns,
            "rows": [list(r) for r in rows],
            "truncated": capped,
            "ms": got.ms,
            **explained,
            "forecast": {
                **forecast.chart_payload(),
                "time_column": time_column,
                "value_column": value_column,
            },
        }
        return json.dumps({"forecast": forecast.summary()}), result

    return forecast_series


def _cannot_forecast(
    code: str, message: str, fixable: bool, sql: str, explained: dict[str, str]
) -> tuple[str, dict[str, Any]]:
    content = json.dumps({"error": {"code": code, "message": message, "fixable": fixable}})
    return content, {"error": message, "at": "forecast", "sql": sql, **explained}
```

(e) Replace `make_tools`:
```python
def make_tools(
    connector: SqlConnector,
    catalog: Catalog,
    with_memory: bool,
    forecaster: ForecastService | None = None,
    today: date | None = None,
) -> list[BaseTool]:
    tools = [make_query_tool(connector, catalog)]
    if forecaster is not None:
        tools.append(make_forecast_tool(connector, catalog, forecaster, today or date.today()))
    if with_memory:
        tools.append(remember)
    return tools
```

- [ ] **Step 6: Register it in `build_agent`**

In `app/agent/graph.py`, change the prompt import to `from app.agent.prompts import AGENT_SYSTEM, capability`, add `from app.forecasting.service import get_forecaster`, and replace `build_agent`'s body:
```python
    forecaster = get_forecaster()
    today = date.today()
    return create_agent(
        model=get_llm(),
        tools=make_tools(
            connector, catalog, store is not None, forecaster=forecaster, today=today
        ),
        system_prompt=AGENT_SYSTEM.format(
            today=today.isoformat(), capability=capability(forecaster is not None)
        ),
        middleware=build_middleware(store is not None) if middleware is None else middleware,
        context_schema=RunContext,
        checkpointer=checkpointer,
        store=store,
    )
```

- [ ] **Step 7: Hash the prompt the cassettes actually replay**

In `evals/recorded.py` `prompt_sha()`, change the `composed` line to:
```python
    # Replay never loads a forecasting model, so it records and replays the prompt production
    # runs today. golden_forecast is live-only: its numbers feed later request hashes.
    composed = prompts.AGENT_SYSTEM.format(
        today="{today}", capability=prompts.capability(forecasting=False)
    )
```

- [ ] **Step 8: Run the tests to verify they pass, then the whole quick suite**

Run: `.venv\Scripts\python -m pytest tests/unit/test_forecast_tool.py tests/unit/test_prompts.py tests/unit/test_agent.py tests/unit/test_tools.py -q --no-cov`
Expected: all pass. `test_tools.py` must pass unchanged, because it proves the refactored query tool behaves identically.

Run: `.venv\Scripts\python -m pytest -m "not integration and not forecast" -q`
Expected: all pass.

- [ ] **Step 9: Lint and commit**

```bash
.venv/Scripts/python.exe -m ruff format app tests evals && .venv/Scripts/python.exe -m ruff check app tests evals
git add app/agent/prompts.py app/agent/tools.py app/agent/graph.py evals/recorded.py tests/unit/test_forecast_tool.py tests/unit/test_prompts.py tests/unit/test_agent.py
git commit -m "feat(agent): a forecast_series tool, offered only when a model is loaded" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The stream, the chart, the saved run and memory

**Files:**
- Modify: `analyst-agent-backend/app/services/charts.py` (add `forecast_chart`)
- Modify: `analyst-agent-backend/app/services/runs.py` (`EventTranslator._for_model` lines 93-97, `_rows` lines 134-152)
- Modify: `analyst-agent-backend/app/api/schemas.py` (`ChartSpec` lines 165-172, `TraceAttempt.at` line 183)
- Modify: `analyst-agent-backend/app/agent/middleware.py` (`_harvest` lines 78-88)
- Test: `tests/unit/test_charts.py`, `tests/unit/test_schemas.py`, `tests/unit/test_agent.py`, `tests/unit/test_middleware.py`

**Interfaces:**
- Consumes:
  - Task 6: the artifact's `forecast` key with `grain`, `interval`, `history`, `points`, `time_column`, `value_column`
  - Task 6: `FORECAST_TOOL_NAME`
  - Task 2: `MIN_HISTORY`, `Grain`
- Produces:
  - `forecast_chart(payload: dict) -> dict` returning `{"type": "forecast", "x", "y": [..], "forecast": {"grain", "interval", "history", "points"}}`
  - The SSE `chart` event carries that dict.
  - `RunOutcome.tool == "forecast"` for a forecast run.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_charts.py` (and import `forecast_chart`):
```python
class TestForecastChart:
    def _payload(self, history: int, horizon: int) -> dict:
        return {
            "grain": "day",
            "interval": 0.8,
            "history": [[f"h{i}", float(i)] for i in range(history)],
            "points": [[f"p{i}", 1.0, 0.0, 2.0] for i in range(horizon)],
            "time_column": "day",
            "value_column": "units",
        }

    def test_it_names_the_axes_the_rows_used(self):
        chart = forecast_chart(self._payload(10, 3))

        assert (chart["type"], chart["x"], chart["y"]) == ("forecast", "day", ["units"])
        assert chart["forecast"]["points"] == self._payload(10, 3)["points"]

    def test_old_history_is_trimmed_so_the_picture_stays_readable(self):
        chart = forecast_chart(self._payload(250, 12))

        assert len(chart["forecast"]["history"]) == MAX_POINTS - 12
        assert chart["forecast"]["history"][-1] == ["h249", 249.0]

    def test_a_long_horizon_still_keeps_enough_history_to_read_it_against(self):
        chart = forecast_chart(self._payload(250, 199))

        assert len(chart["forecast"]["history"]) == 8
```

Append to `tests/unit/test_schemas.py` (import `ChartSpec` and `TraceAttempt` if not already imported):
```python
class TestForecastShapes:
    def test_a_forecast_chart_is_a_valid_saved_chart(self):
        spec = ChartSpec.model_validate(
            {
                "type": "forecast", "x": "month", "y": ["revenue"],
                "forecast": {
                    "grain": "month", "interval": 0.8,
                    "history": [["2026-08", 110.0]],
                    "points": [["2026-09", 115.0, 105.0, 125.0]],
                },
            }
        )  # fmt: skip

        assert spec.forecast is not None and spec.forecast.points[0][3] == 125.0

    def test_a_bar_chart_still_needs_no_forecast(self):
        assert ChartSpec.model_validate({"type": "bar", "x": "r", "y": ["u"]}).forecast is None

    def test_an_attempt_can_have_been_refused_by_the_forecaster(self):
        attempt = TraceAttempt.model_validate({"sql": "SELECT 1", "rejected": True, "at": "forecast"})

        assert attempt.at == "forecast"
```

Append to `tests/unit/test_agent.py`:
```python
class ScriptedConnector:
    """Answers each query in turn with its own columns and rows."""

    kind = "postgres"
    dialect = "postgres"

    def __init__(self, *results):
        self.results = list(results)

    def run_select(self, sql, max_rows):
        columns, rows = self.results.pop(0)
        return columns, rows[:max_rows]


TWELVE_DAYS = [(f"2026-09-{d:02d}", 10 + d) for d in range(12, 0, -1)]


def _forecast_call(call_id="f1"):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "forecast_series",
                "args": {
                    "sql": "select day, n from vehicles order by day desc",
                    "time_column": "day", "value_column": "n",
                    "grain": "day", "horizon": 3, "kind": "total",
                },
                "id": call_id,
            }
        ],
    )  # fmt: skip


class TestAForecastRun:
    def _run(self, *responses, connector=None):
        connector = connector or ScriptedConnector((["day", "n"], TWELVE_DAYS))
        with patch("app.agent.graph.get_forecaster", return_value=ForecastService(FlatEngine())):
            return _run(FakeToolModel(responses=list(responses)), connector)

    def test_it_streams_the_same_stages_and_a_forecast_chart(self):
        events, outcome = self._run(_forecast_call(), AIMessage(content="About 22 a day."))

        assert _stages(events) == ["router", "sql_gen", "sql_guard", "db_exec", "answer"]
        types = [e["type"] for e in events]
        assert types.index("chart") == types.index("rows") + 1
        chart = next(e for e in events if e["type"] == "chart")["data"]
        assert chart["type"] == "forecast" and len(chart["forecast"]["points"]) == 3
        assert outcome.tool == "forecast"

    def test_a_later_query_clears_the_saved_chart_as_the_client_does(self):
        connector = ScriptedConnector(
            (["day", "n"], TWELVE_DAYS), (["vehicleno"], [("KA01",), ("KA02",)])
        )

        _, outcome = self._run(
            _forecast_call(),
            _tool_call("select vehicleno from vehicles"),
            AIMessage(content="Two."),
            connector=connector,
        )

        assert outcome.chart is None
```

Append to `tests/unit/test_middleware.py`. Add these imports:
- `numpy as np`
- `from app.forecasting.engine import EngineForecast`
- `from app.forecasting.service import ForecastService`
```python
class FlatEngine:
    name = "flat"
    max_context = 1024
    max_horizon = 256

    def predict(self, values, horizon):
        mean = np.full(horizon, values[-1])
        return EngineForecast(mean=mean, lower=mean - 1, upper=mean + 1)


class TestAForecastRefusalIsNotACorrection:
    def test_sound_sql_the_forecaster_could_not_use_is_not_filed_as_refused(self):
        # FakeConnector returns only `vehicleno`, so the forecaster refuses for a missing
        # column. The query that follows is the same SQL, and was never wrong.
        store = InMemoryStore()
        forecast = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "forecast_series",
                    "args": {
                        "sql": "select vehicleno from vehicles", "time_column": "day",
                        "value_column": "n", "grain": "day", "horizon": 3, "kind": "total",
                    },
                    "id": "c1",
                }
            ],
        )  # fmt: skip
        model = FakeToolModel(
            responses=[forecast, _tool_call("select vehicleno from vehicles", "c2"), AIMessage(content="One.")]
        )

        with patch("app.agent.graph.get_forecaster", return_value=ForecastService(FlatEngine())):
            run(model, store=store)

        assert store.search(("t_one", "c1", memory.CORRECTIONS)) == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/unit/test_charts.py tests/unit/test_schemas.py tests/unit/test_agent.py tests/unit/test_middleware.py -q --no-cov`
Expected failures:
- `ImportError: cannot import name 'forecast_chart'`
- `ValidationError` for `type: forecast` / `at: forecast`
- the chart type is `line`, not `forecast`
- the correction is filed

- [ ] **Step 3: Add `forecast_chart`**

In `app/services/charts.py`, add `from app.forecasting.preprocessing import MIN_HISTORY`, then append:
```python
def forecast_chart(payload: dict[str, Any]) -> dict[str, Any]:
    """The history a forecast was made from and the forecast itself, as one chart.

    Drawn from the cleaned series rather than the raw rows, because that is what the model was
    given: gaps filled, duplicates merged, an unfinished period dropped. The oldest history is
    trimmed so the whole picture stays within MAX_POINTS, but never below MIN_HISTORY.
    """
    points = payload["points"]
    keep = max(MAX_POINTS - len(points), MIN_HISTORY)
    return {
        "type": "forecast",
        "x": payload["time_column"],
        "y": [payload["value_column"]],
        "forecast": {
            "grain": payload["grain"],
            "interval": payload["interval"],
            "history": payload["history"][-keep:],
            "points": points,
        },
    }
```

- [ ] **Step 4: Teach `EventTranslator` about it**

In `app/services/runs.py`:
- change `from app.services.charts import infer_chart` to `from app.services.charts import forecast_chart, infer_chart`;
- add `from app.agent.tools import FORECAST_TOOL_NAME`.

In `_for_model`, replace `self.outcome.tool = "sql"` with:
```python
            forecasting = any(c["name"] == FORECAST_TOOL_NAME for c in message.tool_calls)
            self.outcome.tool = "forecast" if forecasting else "sql"
```
In `_rows`, replace the chart block (from `chart = infer_chart(` to the end of the method) with:
```python
        forecast = result.get("forecast")
        chart = (
            forecast_chart(forecast)
            if forecast
            else infer_chart(result["columns"], result["rows"], result["truncated"])
        )
        # Assigned even when there is none: the client drops its chart on every new query, and
        # a saved run must show what the live one ended on.
        self.outcome.chart = chart
        if chart:
            yield {"type": "chart", "data": chart}
```

- [ ] **Step 5: Widen the schemas**

In `app/api/schemas.py`, import `Grain` from `app.forecasting.preprocessing`, and replace `ChartSpec` with:
```python
class ForecastChart(BaseModel):
    grain: Grain
    interval: float
    # [period, value] and [period, forecast, low, high]. Lists rather than objects, so a
    # 200-point chart does not repeat four key names two hundred times on every run.
    history: list[tuple[str, float]]
    points: list[tuple[str, float, float, float]]


class ChartSpec(BaseModel):
    """A suggestion rendered beside the table, never instead of it."""

    type: Literal["bar", "line", "forecast"]
    x: str
    # A list, because one month column beside two numeric ones is the commonest shape a
    # spreadsheet produces, and a list costs nothing.
    y: list[str]
    forecast: ForecastChart | None = None
```
In `TraceAttempt`, change the `at` line to `at: Literal["guard", "database", "forecast"] | None = None`.

- [ ] **Step 6: Stop filing forecast refusals as corrections**

In `app/agent/middleware.py` `_harvest`, replace:
```python
        if artifact.get("error"):
            pending = (artifact.get("sql", ""), artifact["error"])
```
with:
```python
        if artifact.get("error"):
            # Only a refused or failed query is a mistake a later query corrects. A forecast the
            # data could not support ran sound SQL, and filing it would later tell the model
            # that SQL had been refused.
            if artifact["at"] in ("guard", "database"):
                pending = (artifact.get("sql", ""), artifact["error"])
```

- [ ] **Step 7: Run the tests to verify they pass, then the whole quick suite**

Run: `.venv\Scripts\python -m pytest -m "not integration and not forecast" -q`
Expected: all pass. The coverage floors are 70% overall and 85% for `sql_guard.py`/`security/`, and they still hold.

- [ ] **Step 8: Lint, typecheck and commit**

```bash
.venv/Scripts/python.exe -m ruff format app tests && .venv/Scripts/python.exe -m ruff check app tests && .venv/Scripts/python.exe -m mypy app
git add app/services/charts.py app/services/runs.py app/api/schemas.py app/agent/middleware.py tests/unit/test_charts.py tests/unit/test_schemas.py tests/unit/test_agent.py tests/unit/test_middleware.py
git commit -m "feat(agent): stream a forecast as a chart, and keep it off the correction list" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Frontend — types and turning a forecast spec into something plottable

**Files:**
- Modify: `analyst-agent-frontend/lib/api/types.ts` (`ChartSpec` lines 152-156, `Attempt.at` line 180)
- Modify: `analyst-agent-frontend/features/ask/run-types.ts` (line 30)
- Modify: `analyst-agent-frontend/features/ask/chart.ts`
- Test: `analyst-agent-frontend/features/ask/chart.test.ts`

**Interfaces:**
- Consumes (Task 7): the SSE `chart` payload `{type: "forecast", x, y: [col], forecast: {grain, interval, history: [label, value][], points: [label, mean, low, high][]}}`
- Produces:
  - `ForecastSeries` type; `ChartSpec.type` includes `"forecast"`; `ChartSpec.forecast?: ForecastSeries | null`
  - `Attempt.at` includes `"forecast"`
  - `PlottableChart.band?: ({ lo: number; hi: number } | null)[]`, `PlottableChart.split?: number`, `PlottableChart.interval?: number`
  - `forecastTable(spec: ChartSpec): ResultTable | null`

- [ ] **Step 1: Write the failing tests**

Append to `features/ask/chart.test.ts` (and import `forecastTable` from `./chart` and `type ChartSpec` from `@/lib/api/types`):
```ts
const FORECAST: ChartSpec = {
  type: "forecast",
  x: "month",
  y: ["revenue"],
  forecast: {
    grain: "month",
    interval: 0.8,
    history: [
      ["2026-06", 100],
      ["2026-07", 120],
      ["2026-08", 110],
    ],
    points: [
      ["2026-09", 115, 105, 125],
      ["2026-10", 118, 100, 136],
    ],
  },
};

// The table shows the raw rows; a forecast draws from the cleaned series in its spec.
const NO_ROWS: ResultTable = { columns: [], rows: [], truncated: false };

function drawn(spec: ChartSpec) {
  const chart = buildChart(spec, NO_ROWS);
  if (chart.kind !== "chart") throw new Error(`expected a chart, got: ${chart.reason}`);
  return chart;
}

describe("buildChart for a forecast", () => {
  it("runs the forecast periods on after the history", () => {
    const chart = drawn(FORECAST);

    expect(chart.categories).toEqual(["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]);
    expect(chart.split).toBe(2);
  });

  it("draws actuals only across the history", () => {
    expect(drawn(FORECAST).series[0].points.map((p) => p?.value ?? null)).toEqual([
      100, 120, 110, null, null,
    ]);
  });

  it("starts the forecast on the last actual point so the two lines meet", () => {
    const forecast = drawn(FORECAST).series[1];

    expect(forecast.column).toBe("forecast");
    expect(forecast.points.map((p) => p?.value ?? null)).toEqual([null, null, 110, 115, 118]);
  });

  it("fans the range out from the last actual point", () => {
    expect(drawn(FORECAST).band).toEqual([
      null,
      null,
      { lo: 110, hi: 110 },
      { lo: 105, hi: 125 },
      { lo: 100, hi: 136 },
    ]);
  });

  it("scales to the top of the range, not just the forecast line", () => {
    const chart = drawn(FORECAST);

    expect(chart.max).toBe(136);
    expect(chart.min).toBe(0);
  });
});

describe("forecastTable", () => {
  it("lists each forecast period with its range", () => {
    expect(forecastTable(FORECAST)).toEqual({
      columns: ["month", "revenue forecast", "low (80%)", "high (80%)"],
      rows: [
        ["2026-09", 115, 105, 125],
        ["2026-10", 118, 100, 136],
      ],
      truncated: false,
    });
  });

  it("is nothing for any other chart", () => {
    expect(forecastTable({ type: "line", x: "month", y: ["revenue"] })).toBeNull();
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm test -- features/ask/chart.test.ts`
Expected: FAIL. TypeScript/vitest reports that `forecastTable` is not exported, and `type: "forecast"` is not assignable.

- [ ] **Step 3: Widen the types**

In `lib/api/types.ts`, replace `ChartSpec`:
```ts
/** A forecast's own series: the cleaned history it was made from, then what it predicts. */
export type ForecastSeries = {
  grain: "hour" | "day" | "week" | "month" | "quarter" | "year";
  /** How much of the outcome the low-to-high band is meant to hold, e.g. 0.8. */
  interval: number;
  /** [period, value], oldest first. */
  history: [string, number][];
  /** [period, forecast, low, high]. */
  points: [string, number, number, number][];
};

export type ChartSpec = {
  type: "bar" | "line" | "forecast";
  x: string;
  y: string[];
  forecast?: ForecastSeries | null;
};
```
In `Attempt`, change `at?: "guard" | "database" | null;` to `at?: "guard" | "database" | "forecast" | null;`.

In `features/ask/run-types.ts` line 30, change `at: "guard" | "database"` to `at: "guard" | "database" | "forecast"`.

- [ ] **Step 4: Build the forecast branch**

In `features/ask/chart.ts`:

(a) Change the import to `import type { ChartSpec, ForecastSeries } from "@/lib/api/types";`.

(b) Add three optional fields to `PlottableChart`:
```ts
  /** Forecast only: the low-to-high range at each category, null where there is none. */
  band?: ({ lo: number; hi: number } | null)[];
  /** Forecast only: the index of the last actual point, where the forecast takes over. */
  split?: number;
  /** Forecast only: how much of the outcome the band is meant to hold. */
  interval?: number;
```

(c) Make `forecastChart` the first line of `buildChart`:
```ts
export function buildChart(spec: ChartSpec, result: ResultTable): PlottableChart | NoChart {
  // Drawn from the spec alone: it carries the cleaned series the forecast was made from,
  // which is not the raw rows the table below shows.
  if (spec.type === "forecast" && spec.forecast) return forecastChart(spec, spec.forecast);
  if (result.rows.length === 0) return { kind: "none", reason: "The query matched nothing." };
```

(d) Append:
```ts
function forecastChart(spec: ChartSpec, forecast: ForecastSeries): PlottableChart | NoChart {
  const { history, points, interval } = forecast;
  if (history.length === 0 || points.length === 0) {
    return { kind: "none", reason: "The forecast has nothing to draw." };
  }

  const split = history.length - 1;
  const [, last] = history[split];
  const actual = [...history.map(([, value]) => point(value)), ...points.map(() => null)];
  // Starts on the last actual point, so the dashed line leaves from where the solid one ends
  // and the band fans out from a single point rather than appearing from nowhere.
  const predicted = [
    ...history.map((_, i) => (i === split ? point(last) : null)),
    ...points.map(([, mean]) => point(mean)),
  ];
  const band = [
    ...history.map((_, i) => (i === split ? { lo: last, hi: last } : null)),
    ...points.map(([, , lo, hi]) => ({ lo, hi })),
  ];
  const values = [
    ...history.map(([, value]) => value),
    ...points.flatMap(([, mean, lo, hi]) => [mean, lo, hi]),
  ];

  return {
    kind: "chart",
    type: "forecast",
    xColumn: spec.x,
    categories: [...history.map(([period]) => period), ...points.map(([period]) => period)],
    series: [
      { column: spec.y[0], points: actual },
      { column: "forecast", points: predicted },
    ],
    band,
    split,
    interval,
    min: Math.min(0, ...values),
    max: Math.max(0, ...values),
  };
}

/** The forecast as rows, for the table under the chart. */
export function forecastTable(spec: ChartSpec): ResultTable | null {
  if (spec.type !== "forecast" || !spec.forecast) return null;
  const percent = `${Math.round(spec.forecast.interval * 100)}%`;
  return {
    columns: [spec.x, `${spec.y[0]} forecast`, `low (${percent})`, `high (${percent})`],
    rows: spec.forecast.points.map(([period, mean, lo, hi]) => [period, mean, lo, hi]),
    truncated: false,
  };
}
```
`point(value)` is the existing helper at `chart.ts:59`. A finite number is a numeric cell, so it never returns null here. If TypeScript complains that `point(...)` may be null inside `actual` and `predicted`, that is correct as typed, because `ChartSeries.points` is `(ChartPoint | null)[]`.

- [ ] **Step 5: Run the tests to verify they pass, then typecheck**

Run: `npm test -- features/ask/chart.test.ts`
Expected: all pass, including the 15 existing `buildChart` cases.

Run: `npm run typecheck`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
cd ../analyst-agent-frontend
git add lib/api/types.ts features/ask/run-types.ts features/ask/chart.ts features/ask/chart.test.ts
git commit -m "feat(web): read a forecast chart spec into history, forecast and range" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Frontend — draw it, tabulate it, and name it

**Files:**
- Modify: `analyst-agent-frontend/components/ask/result-chart.tsx`
- Modify: `analyst-agent-frontend/components/ask/ask-workspace.tsx` (the `Turn` component, around lines 254-280)
- Modify: `analyst-agent-frontend/features/ask/run-process.ts`
- Modify: `analyst-agent-frontend/components/ask/run-process.tsx` (lines 29-31 and 93)
- Test: `analyst-agent-frontend/features/ask/run-process.test.ts`

**Interfaces:**
- Consumes (Task 8): `PlottableChart.band/split/interval` and `forecastTable(spec)`
- Produces:
  - `REFUSAL_LABEL: Record<"guard" | "database" | "forecast", string>`
  - `toolLabel(tool: string | null): string | null`
  - `liveTool(state: Pick<RunState, "stageLog" | "chart" | "attempts">): "forecast" | "sql" | null`

- [ ] **Step 1: Write the failing tests**

Append to `features/ask/run-process.test.ts` (and import `liveTool`, `toolLabel` from `./run-process`):
```ts
describe("which tool answered", () => {
  it("names a saved run's tool the way the agent does", () => {
    expect(toolLabel("sql")).toBe("query_database");
    expect(toolLabel("forecast")).toBe("forecast_series");
    expect(toolLabel(null)).toBeNull();
  });

  it("knows a live forecast by its chart", () => {
    const chart = { type: "forecast" as const, x: "month", y: ["revenue"] };

    expect(liveTool({ stageLog: ["router", "sql_gen", "sql_guard"], attempts: [], chart })).toBe("forecast");
  });

  it("knows a forecast that could not be made by its refusal", () => {
    const attempts: Attempt[] = [{ sql: "SELECT 1", rejected: true, reason: "only 5 months", at: "forecast" }];

    expect(liveTool({ stageLog: ["router", "sql_gen", "sql_guard"], attempts, chart: null })).toBe("forecast");
  });

  it("calls any other checked query a query", () => {
    expect(liveTool({ stageLog: ["router", "sql_gen", "sql_guard"], attempts: [], chart: null })).toBe("sql");
    expect(liveTool({ stageLog: ["router", "answer"], attempts: [], chart: null })).toBeNull();
  });
});

describe("a forecast the data could not support", () => {
  it("says it couldn't forecast, not that the query was rejected", () => {
    const attempts: Attempt[] = [{ sql: "SELECT 1", rejected: true, reason: "only 5 months", at: "forecast" }];

    const steps = buildProcessSteps(["router", "sql_gen", "sql_guard", "answer"], attempts, "done");

    expect(steps[2].note).toBe("couldn't forecast");
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `npm test -- features/ask/run-process.test.ts`
Expected: FAIL, because `toolLabel`/`liveTool` are not exported and the note reads `rejected`.

- [ ] **Step 3: Add the labels to `run-process.ts`**

In `features/ask/run-process.ts`, change the import to `import type { Attempt, RunState, Stage } from "./run-types";` and add below `STAGE_LABEL`:
```ts
/** Why an attempt went no further, by where it stopped. */
export const REFUSAL_LABEL: Record<NonNullable<Attempt["at"]>, string> = {
  guard: "Rejected",
  database: "Failed in the database",
  forecast: "Couldn't forecast",
};

/** A saved run's tool, named the way the agent names it. */
export function toolLabel(tool: string | null): string | null {
  if (tool === "sql") return "query_database";
  if (tool === "forecast") return "forecast_series";
  return tool;
}

/**
 * A live run has no `tool` field until it is saved. A forecast shows itself by its chart, or
 * by its refusal when the data could not support one; anything else that reached the guard
 * was a query.
 */
export function liveTool(state: Pick<RunState, "stageLog" | "chart" | "attempts">): "forecast" | "sql" | null {
  if (state.chart?.type === "forecast" || state.attempts.some((a) => a.at === "forecast")) return "forecast";
  return state.stageLog.includes("sql_guard") ? "sql" : null;
}
```
In `buildProcessSteps`, replace:
```ts
      rejected ? (query.at === "database" ? "failed in the database" : "rejected")
```
with:
```ts
      rejected ? REFUSAL_LABEL[query.at ?? "guard"].toLowerCase()
```

- [ ] **Step 4: Use them in `run-process.tsx`**

Change the run-process import to include `liveTool, REFUSAL_LABEL, toolLabel`, and replace the `const tool = ...` block (lines 29-31) with:
```ts
  const tool = toolLabel(state ? liveTool(state) : detail!.tool);
```
In `RefusedQueries`, replace `label={attempt.at === "database" ? "Failed in the database" : "Rejected"}` with:
```tsx
label={REFUSAL_LABEL[attempt.at ?? "guard"]}
```

- [ ] **Step 5: Draw the forecast in `result-chart.tsx`**

(a) In `ResultChart`, replace the `figcaption` text span's content:
```tsx
          {chart.type === "forecast"
            ? `${chart.series[0].column} by ${chart.xColumn}, with a forecast`
            : `${chart.series.map((s) => s.column).join(", ")} by ${chart.xColumn}`}
```

(b) In `Legend`, after the `chart.series.map(...)` list items, add:
```tsx
      {chart.band && chart.interval !== undefined ? (
        <li className="flex items-center gap-2">
          <span aria-hidden className="h-2.5 w-2.5 rounded-xs bg-series-3 opacity-60" />
          <span className="font-mono text-[0.75rem] text-ink-muted">
            {Math.round(chart.interval * 100)}% range
          </span>
        </li>
      ) : null}
```

(c) In `Line`, inside the `<svg>` directly after the zero `<line>`, add the band and the divider:
```tsx
        {chart.band ? (
          <polygon className="fill-series-3 opacity-60" points={bandPoints(chart.band, x, y)} />
        ) : null}

        {chart.split !== undefined ? (
          <line
            x1={x(chart.split)}
            y1={0}
            x2={x(chart.split)}
            y2={LINE_HEIGHT}
            className="stroke-line-strong"
            strokeWidth={1}
            strokeDasharray="3 3"
          />
        ) : null}
```
On the series `<polyline>`, add a dash for the forecast series only:
```tsx
              strokeDasharray={chart.type === "forecast" && i === 1 ? "6 5" : undefined}
```
Replace the x-label row under the svg with:
```tsx
      <div className="relative mt-1 flex justify-between font-mono text-[0.75rem] text-ink-muted">
        <span>{chart.categories[0]}</span>
        {chart.split !== undefined ? (
          <span
            className="absolute -translate-x-1/2 text-ink"
            style={{ left: `${(x(chart.split) / LINE_WIDTH) * 100}%` }}
          >
            {chart.categories[chart.split]}
          </span>
        ) : null}
        <span>{chart.categories[chart.categories.length - 1]}</span>
      </div>
```

(d) Append the helper below `lastPoint`:
```tsx
/** The band as one closed shape: along the top edge left to right, back along the bottom. */
function bandPoints(
  band: ({ lo: number; hi: number } | null)[],
  x: (index: number) => number,
  y: (value: number) => number,
): string {
  const edge = band.flatMap((b, index) => (b ? [{ index, ...b }] : []));
  const top = edge.map((p) => `${x(p.index)},${y(p.hi)}`);
  const bottom = [...edge].reverse().map((p) => `${x(p.index)},${y(p.lo)}`);
  return [...top, ...bottom].join(" ");
}
```

(e) In `summarise`, prefix the forecast case:
```tsx
  if (chart.type === "forecast" && chart.split !== undefined) {
    const ahead = chart.categories.length - chart.split - 1;
    return `${chart.series[0].column} by ${chart.xColumn}, ${chart.split + 1} actual points then a ${ahead}-point forecast, from ${chart.min} to ${chart.max}.`;
  }
```

- [ ] **Step 6: Show the forecast table in `ask-workspace.tsx`**

Import `forecastTable` alongside `buildChart` from `@/features/ask/chart`. In `Turn`, after `plottable`:
```tsx
  const forecast = turn.chart ? forecastTable(turn.chart) : null;
```
and between the chart and the history table:
```tsx
        {forecast ? <ResultTable result={forecast} /> : null}
```

- [ ] **Step 7: Run all frontend checks**

Run: `npm test`
Expected: all pass.

Run: `npm run typecheck && npm run lint`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add components/ask/result-chart.tsx components/ask/ask-workspace.tsx components/ask/run-process.tsx features/ask/run-process.ts features/ask/run-process.test.ts
git commit -m "feat(web): draw a forecast with its range, list it, and name the tool" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Eval fixture and cases

**Files:**
- Create: `analyst-agent-backend/evals/fixtures/monthly_revenue.csv`
- Create: `analyst-agent-backend/evals/golden_forecast.yaml`
- Modify: `analyst-agent-backend/evals/golden_sql.yaml` (append one case)

- [ ] **Step 1: Generate the fixture deterministically**

From `analyst-agent-backend`:
```bash
.venv/Scripts/python.exe - <<'EOF'
# Three years of month-start revenue: a steady rise with a festive-season peak and a monsoon
# dip, so a forecast has both a trend and a season to find. Every month's revenue is unique.
SEASON = {1: -4000, 2: -6000, 3: 8000, 4: 2000, 5: -2000, 6: -8000,
          7: -10000, 8: -6000, 9: 4000, 10: 14000, 11: 12000, 12: 6000}
lines = ["month,revenue_inr,units"]
for k in range(36):
    year, month = 2023 + (8 + k) // 12, (8 + k) % 12 + 1
    revenue = 100000 + 2000 * k + SEASON[month]
    lines.append(f"{year}-{month:02d}-01,{revenue},{revenue // 250}")
open("evals/fixtures/monthly_revenue.csv", "w", newline="\n").write("\n".join(lines) + "\n")
EOF
head -3 evals/fixtures/monthly_revenue.csv; tail -1 evals/fixtures/monthly_revenue.csv; grep 2026-03 evals/fixtures/monthly_revenue.csv
```
Expected: `2023-09-01,104000,416` first, `2026-08-01,164000,656` last, and `2026-03-01,168000,672`.

- [ ] **Step 2: Write the forecast suite**

`evals/golden_forecast.yaml`:
```yaml
# Forecasting questions, run live only, with FORECAST_ENGINE=timesfm, against
# evals/fixtures/monthly_revenue.csv (36 months, 2023-09 to 2026-08).
#
#   curl -X POST localhost:8000/connections/file -H "Authorization: Bearer $env:TOKEN" `
#        -F name="monthly revenue" -F files=@evals/fixtures/monthly_revenue.csv
#   $env:CONN="<that connection id>"; python evals/run_evals.py --cases golden_forecast.yaml
#
# Not replayable: the forecast's numbers go back to the model, so they are part of every later
# request the cassette would have to match, and they come from a model the replay never loads.
#
# Every forecast case carries `expect_type: rows` because run_evals needs one primary
# expectation; the history rows are what satisfies it. `expect_chart: forecast` is the
# assertion that matters: it is only emitted when the forecast tool ran and succeeded.

- q: Forecast revenue for the next six months.
  expect_type: rows
  expect_chart: forecast

- q: Predict next month's revenue.
  expect_type: rows
  expect_chart: forecast

- q: Estimate how many units we will sell next quarter.
  expect_type: rows
  expect_chart: forecast

# History must stay with the query tool. 168000 is March 2026's revenue and no other month's.
- q: What was the revenue in March 2026?
  expect_value: 168000

- q: Show revenue by month.
  expect_type: rows
  expect_chart: line
```

- [ ] **Step 3: Add the both-modes case to the SQL suite (rule 6)**

Append to `evals/golden_sql.yaml`:
```yaml

# Added with forecasting: a history question worded like a trend, which has to stay with the
# query tool whether or not a forecasting model is loaded. No `expect_chart`: Postgres dates
# reach the chart rule as strings through MCP, so it draws a bar here.
- q: How has battery revenue moved month by month?
  expect_type: rows
```

- [ ] **Step 4: Check the YAML parses, then commit**

```bash
.venv/Scripts/python.exe -c "import yaml; [yaml.safe_load(open(f'evals/{n}.yaml')) for n in ('golden_forecast','golden_sql')]; print('ok')"
git add evals/fixtures/monthly_revenue.csv evals/golden_forecast.yaml evals/golden_sql.yaml
git commit -m "feat(agent): forecast eval fixture and cases" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: End-to-end check, the eval gate, cassettes and docs

**Files:**
- Modify: `analyst-agent-backend/docs/CLAUDE.md` (the SSE contract table at lines 146-155, and the architecture paragraph at line 120)
- Modify: `analyst-agent-backend/docs/STATUS.md` (a new section at the end)
- Modify: `analyst-agent-backend/docs/DEVELOPMENT.md` (the commands section)
- Replace: `analyst-agent-backend/evals/cassettes/golden_sql.*.json`, `golden_file.*.json` (re-recorded under the new prompt hash)

- [ ] **Step 1: End to end with forecasting on**

Check free commit memory first; it needs more than 3 GB.

Start the MCP server as in Task 1. Then start the API with forecasting on:
```powershell
Start-Process powershell -ArgumentList '-NoExit','-Command','cd D:\itarang-agents\analyst-agent-backend; $env:OPENBLAS_NUM_THREADS="1"; $env:HF_HOME="D:\hf-cache"; $env:FORECAST_ENGINE="timesfm"; $env:MAX_RUNS_PER_MINUTE="100"; .venv\Scripts\python -m uvicorn app.main:app --port 8000'
```
Expected: the log shows `startup` after the model loads, taking seconds rather than minutes. Then start the frontend (`npm run dev` in `analyst-agent-frontend`) and upload `monthly_revenue.csv` through the Connections page.

In the Ask page, check each of these and note the results:
1. **"Forecast revenue for the next six months."**
   - The chart shows a solid line to 2026-08, a dashed line on to 2027-02, a shaded range fanning out from 2026-08, and a dotted divider labelled 2026-08.
   - A six-row forecast table sits under the chart, above the 36-row history table.
   - The answer calls the figures a forecast, gives a range, and says the history runs 2023-09 to 2026-08.
   - "How this was answered" shows the Tool as `forecast_series`.
2. **"What was the revenue in March 2026?"** The Tool is `query_database`, and the answer is 168,000.
3. **Too little history.** Using the `sales.csv` connection (three months), ask "Forecast revenue for the next six months." The answer explains there isn't enough history, with no fabricated numbers. The process shows "Couldn't forecast", and there are no repeated attempts.

- [ ] **Step 2: The rule 6 gate**

**With forecasting off**, restart the API without `FORECAST_ENGINE`. Then run, for each connection:
```powershell
.venv\Scripts\python evals/run_evals.py --cases golden_file.yaml   # CONN = sales.csv connection
.venv\Scripts\python evals/run_evals.py --cases golden_pdf.yaml    # CONN = statement.pdf connection
.venv\Scripts\python evals/run_evals.py --cases golden_sql.yaml    # CONN = demo Postgres connection
```

**With forecasting on**, restart with `FORECAST_ENGINE=timesfm` and run the same three, plus:
```powershell
.venv\Scripts\python evals/run_evals.py --cases golden_forecast.yaml   # CONN = monthly_revenue connection
```

Expected: no suite drops below its Task 1 baseline (`golden_file` 6/7, `golden_pdf` 4/4, `golden_sql` as measured), and `golden_forecast` is at or above 80%.

If any suite drops, stop. Read the failing answers and adjust the wording in `FORECAST_CAPABILITY`/`FORECAST_OFF`. Commit that as `fix(agent): …` and re-run the gate. Do not merge with a lower pass rate.

- [ ] **Step 3: Re-record the replay cassettes for the forecasting-off prompt**

The prompt hash changed in Task 6, so the old cassettes no longer match. The free tier is about 20 requests per day per model, so record in slices:
```powershell
$env:CONN="<sales.csv connection>"; .venv\Scripts\python evals/recorded.py --record --cases golden_file.yaml --only 0-6
$env:CONN="<demo connection>";     .venv\Scripts\python evals/recorded.py --record --cases golden_sql.yaml --only 0-3
# next day, if the quota ran out:
$env:CONN="<demo connection>";     .venv\Scripts\python evals/recorded.py --record --cases golden_sql.yaml --only 4-9
.venv\Scripts\python evals/recorded.py --replay --cases golden_file.yaml
.venv\Scripts\python evals/recorded.py --replay --cases golden_sql.yaml
```
Expected: each replay scores the same as its live run. Delete the stale `evals/cassettes/*.de39cc3c.json`. If the quota blocks finishing today, record which slices are left in STATUS and carry on. The live gate in Step 2 is the merge criterion, not the cassettes.

- [ ] **Step 4: Update the docs**

In `docs/CLAUDE.md`, change the SSE table rows:
```
| `rejected` | `{"sql": "...", "reason": "...", "at": guard\|database\|forecast}` — always straight after `status: sql_guard` |
| `chart` | `{"type": bar\|line\|forecast, "x": "col", "y": ["col"], "forecast"?: {"grain", "interval", "history": [[period, value]], "points": [[period, forecast, low, high]]}}` — optional, always straight after a `rows` |
```
Add a paragraph under the table:
```
`forecast` and `at: forecast` were added on 2026-09-22 the same way: additive, no new stage, both
clients in one change. A forecast run goes through the same four stages, because the forecast tool
writes SQL, guards it and runs it before it forecasts. Its `rows` are the history the SQL returned,
and the chart carries the cleaned series and the forecast, which the table under it lists.
```
In the architecture paragraph (line 120), after `app/catalog/ (...)`, add:
`· app/forecasting/ (preprocessing.py rows to a clean series, engine.py the ForecastEngine protocol and TimesFMEngine — the only code importing timesfm or torch, lazily — service.py the one model per process; imports nothing from app.agent)`

In `docs/DEVELOPMENT.md`, add a "Forecasting" subsection under the commands:
```
Forecasting is off unless `FORECAST_ENGINE=timesfm`. To run it locally:

    $env:HF_HOME = "D:\hf-cache"          # the checkpoint is ~0.9 GB; C: has no room
    pip install -e ".[forecast]"          # timesfm 2.0.2 + CPU torch; never in requirements.lock
    pytest -m forecast                    # the real-model tests
    $env:FORECAST_ENGINE = "timesfm"; $env:OPENBLAS_NUM_THREADS = "1"; uvicorn app.main:app

Check free commit memory first (> 3 GB). The quick suite is `pytest -m "not integration and not forecast"`.
```

In `docs/STATUS.md`, append a section "Forecasting with TimesFM (2026-09-22)". It covers:
- the design in one paragraph, linking the spec;
- the Task 4 measurements: load seconds, RSS in MB and prediction milliseconds;
- the eval table: suite × (before, after off, after on), plus `golden_forecast`;
- the cassette state;
- **"Turning it on in production"**:
  - a ≥ 2 GB instance, since Render Standard is the smallest that fits;
  - install torch from `https://download.pytorch.org/whl/cpu` so Linux doesn't pull CUDA wheels;
  - download the checkpoint during the build into a directory inside the project, with `HF_HOME` pointing there, so it isn't fetched on every start;
  - set `FORECAST_ENGINE=timesfm`;
  - with the queue on, the worker service needs the memory, not the API.

- [ ] **Step 5: Final verification and commit**

Run from `analyst-agent-backend`: `.venv\Scripts\python -m pytest -m "not integration and not forecast" -q`, `.venv\Scripts\python -m ruff check app tests evals`, `.venv\Scripts\python -m mypy app`.
Run from `analyst-agent-frontend`: `npm test`, `npm run typecheck`, `npm run lint`.
Expected: everything green.

```bash
git add docs/CLAUDE.md docs/STATUS.md docs/DEVELOPMENT.md evals/cassettes
git commit -m "docs(status): forecasting with TimesFM, measured, and the eval gate" -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

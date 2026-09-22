# TimesFM forecasting as a `forecast_series` tool

## Context

People ask the Data Analysis Agent forward-looking questions: "forecast revenue for the next six months", "estimate battery demand for the next 30 days". Today it can only look backwards. It has one SQL tool (`query_database`), and `AGENT_SYSTEM` forbids it from estimating any figure. This change adds forecasting as a second agent tool. It is backed by Google's TimesFM, which runs inside the FastAPI process. The design:

- The LLM decides when to forecast, writes the SQL for the history, and explains the result.
- A forecasting module that knows nothing about LLMs or databases cleans the series and runs the model.

**Decisions already made:**

- **Model: TimesFM 2.5** (`google/timesfm-2.5-200m-pytorch`, Apache-2.0), installed as `timesfm[torch]==2.0.2`. That package exposes `timesfm.TimesFM_2p5_200M_torch` and `ForecastConfig`. TimesFM 3.0 (PyPI 3.x) is ruled out because its weights are "restricted to non-commercial, non-production use".
- **Off in production for now** (your choice). The Render backend has 512 MB, shared by the API and MCP processes. TimesFM plus torch adds an estimated 1.1–1.3 GB resident. So `FORECAST_ENGINE` defaults to `off`:
  - With it off, the tool is not registered and the prompt says forecasting is unavailable.
  - The last section lists what turning it on later needs.
- **The TimesFM code stays inside the backend** (`app/forecasting/`). No Space, no separate service.

## Architecture

```
agent (create_agent loop)
  └─ forecast_series(sql, time_column, value_column, grain, horizon, kind, what, why)   app/agent/tools.py
       ├─ guard + connector.run_select             (shared helper with query_database; guard unchanged)
       ├─ prepare_series(columns, rows, ...)       app/forecasting/preprocessing.py  → Series
       └─ forecaster.forecast(series, horizon)     app/forecasting/service.py        → Forecast
             └─ ForecastEngine.predict(values, h)  app/forecasting/engine.py (TimesFMEngine)
  artifact → EventTranslator → sql / rows / chart{type:"forecast"} SSE events → web chart + forecast table
```

The layering rules:

- `preprocessing.py` and `engine.py` import nothing from `app`.
- `service.py` imports only `app.config`, and only in `load_forecaster`.
- The module never sees SQL or a connection, only a cleaned numeric series.
- Only `engine.py` touches `timesfm` or `torch`, and it imports them lazily inside `TimesFMEngine.__init__`. With the setting off, neither is imported.

**Why one tool that takes SQL**, not query-then-forecast:

- The existing guard stays the security boundary.
- A forecast costs one of the six tool calls in `max_tool_calls`, not two.
- History rows stay out of the model's context.
- No state has to pass between tool calls.

## Backend

### 1. `app/forecasting/engine.py`: the replaceable part

- `EngineForecast` is a frozen dataclass: `mean`, `lower`, `upper`, each an `np.ndarray` of length `h`.
- `ForecastEngine(Protocol)` defines `name`, `max_context`, `max_horizon` and `predict(values: np.ndarray, horizon: int) -> EngineForecast`. It is the only interface the service depends on. Chronos or a statistical model later means one new class, with no change to the tool or the agent.
- `TimesFMEngine`:
  - Setup: `from_pretrained(checkpoint)`, then `compile(ForecastConfig(max_context=1024, max_horizon=256, normalize_inputs=True, use_continuous_quantile_head=True, force_flip_invariance=True, infer_is_positive=True, fix_quantile_crossing=True))`.
  - `torch.set_num_threads(threads)`.
  - No `torch_compile`, because it needs a C++ toolchain on Windows and slows startup.
  - One warm-up forecast at load.
  - `predict` calls `model.forecast(horizon=h, inputs=[values])`. It returns the point forecast, quantile index 1 (p10) and index 9 (p90), which makes an **80% interval**.

### 2. `app/forecasting/preprocessing.py`: raw rows to a clean series

`prepare_series(columns, rows, time_column, value_column, grain, kind, today) -> Series` works on only the two named columns:

1. **Find both columns** by exact name. A missing one raises `missing_column`, which lists the columns that exist.
2. **Empty rows** raise `empty`.
3. **Timestamps become naive wall-clock times, one value at a time:**
   - `datetime.fromisoformat` for strings (Postgres values arrive as ISO strings through MCP JSON);
   - `.replace(tzinfo=None)` for aware datetimes;
   - `date`/naive `datetime` values as they are.

   This avoids pandas 3 raising `Mixed timezones detected` on `timestamptz` across a DST change. It also avoids a UTC conversion moving a local-midnight month bucket into the previous month. Any `ValueError` raises `bad_timestamps`.
4. **Values:** `pd.to_numeric(errors="coerce")` handles Decimal, int, float and numeric strings. A non-null value that won't parse raises `not_numeric`, quoting one example. **Null values are dropped before grouping**, so a period with only nulls counts as missing and is filled at step 7. The series never holds NaN.
5. **Align to the grain:** `to_period`. Frequencies are `h`, `D`, `W-SUN` (Monday-start weeks, matching `date_trunc('week')`), `M`, `Q`, `Y`. Duplicate timestamps and periods are merged by `groupby`:
   - `kind="total"` → `sum()`
   - `kind="level"` → `mean()`
6. **Drop the last period if it contains `today`**, so a half-finished month doesn't drag "next month" down. It is recorded as `dropped_partial`.
7. **Reindex to the full `period_range`:**
   - More than `MAX_MISSING_SHARE = 0.3` missing raises `too_sparse` (use a coarser grain).
   - `total` → `fillna(0)`: no rows means nothing sold.
   - `level` → linear interpolation: the endpoints always exist after step 4.
8. **Minimum history:** fewer than `MIN_HISTORY = 8` periods raises `insufficient_history`.

Supporting types:

- `Series` is a frozen dataclass: `periods: pd.PeriodIndex`, `values: np.ndarray[float64]`, `grain`, `kind`, and plain-`int`/`str` notes `filled`, `merged`, `dropped_partial`.
- `ForecastInputError(code, message, fixable)`:
  - `fixable=True` means the model should change its call: missing column, bad types, too sparse, wrong order.
  - `fixable=False` means it should explain to the person: empty, insufficient history, horizon too long.
- Period labels: an ISO start date for hour, day and week; `YYYY-MM`, `YYYYQn` and `YYYY` for the others.

### 3. `app/forecasting/service.py`: lifecycle and the single entry point

- **`ForecastService(engine).forecast(series, horizon) -> Forecast`:**
  1. Checks `1 ≤ horizon ≤ min(engine.max_horizon, len(series))`. This is the only upper-bound check; the tool's schema has only `ge=1`. Too far ahead raises `horizon_too_long`, which is not fixable.
  2. Passes `values[-engine.max_context:]` to the engine.
  3. Generates future periods from `periods[-1] + 1 … + h`.
  4. Rejects non-finite output as `ForecastEngineError`. Any exception from `predict` is re-raised as `ForecastEngineError`.
  5. Converts every output to plain Python `float`/`int`/`str`, because NaN and `np.int64` break `json.dumps` and the `Run.chart` JSON column.
- **Concurrency:** inference runs under a `threading.Lock`. Tools already run on worker threads (`asyncio.to_thread` in `_stream_inline`, and the arq worker), and parallel torch calls would only fight over the same CPU cores. A single short series runs in under a second.
- **Singleton, in the same module-global style as `queue._pool` and `store._in_memory`:**
  - `load_forecaster()` builds `ForecastService(TimesFMEngine(...))` once when `forecast_engine == "timesfm"`. It does nothing when the setting is off or a service is already loaded.
  - `get_forecaster() -> ForecastService | None`.
- **`Forecast`** is a frozen dataclass with two views:
  - `summary()`, the compact dict the model sees;
  - `chart_payload()`, the history and point lists.

### 4. Startup: load once

- **API:** `app/main.py` `lifespan` gets `if s.forecast_engine != "off" and not s.queue_enabled: await asyncio.to_thread(load_forecaster)`.
  - It runs off the event loop, and a failed load fails the boot, as the MCP probe does.
  - In queue mode the API never runs tools, so it skips the roughly 1.2 GB load.
- **Worker:** `app/workers/runs.py` `_startup` loads it whenever the setting is on.
- **Tests:** they never run the lifespan, so nothing loads.

### 5. Settings: `app/config.py`, `.env.example`

- `forecast_engine: Literal["off", "timesfm"] = "off"`
- `forecast_checkpoint: str = "google/timesfm-2.5-200m-pytorch"`
- `forecast_threads: int = 2`

### 6. The tool: `app/agent/tools.py`

- **Shared helper.** Pull the guard-then-run block of `query_database` into one helper that returns a single small tagged result: either a refusal (`content`, `artifact`) or the selection (`safe_sql`, `cols`, `rows`, `ms`). Both tools use it, so rejection strings and artifacts stay identical.
- **`make_forecast_tool(connector, catalog, forecaster, today)`** builds its args with `create_model`, so the SQL argument names the dialect. The args:
  - `sql`
  - `time_column`
  - `value_column`
  - `grain: Literal[hour, day, week, month, quarter, year]`
  - `horizon: int = Field(ge=1)`
  - `kind: Literal["total", "level"]`
  - `what` and `why`, defaulted `""`.
- **History cap is `max_rows` (500)**, the same as the query tool. The MCP server re-caps every Postgres query at its own `max_rows` (`database_mcp.py:97, 201`), and that cap is deliberately the server's own. Five hundred periods is plenty: 41 years of months, 16 months of days.
  - The SQL argument asks for **newest first**, with the period cast to a date (`date_trunc(...)::date` / `CAST(... AS DATE)`).
  - If more than `max_rows` rows come back newest first, the forecast uses the latest 500 and notes `capped`.
  - If they come back oldest first, the tool returns a fixable `wrong_order` error.
- **`today`** is passed in from `build_agent`, the same `graph.date` the tests freeze.
- **On success** it returns `content_and_artifact`:
  - **Content** is JSON: `{"forecast": {grain, kind, horizon, interval: "80%", history: {periods, from, to, last_value, filled_gaps, dropped_partial, capped}, lead_in: [{period, forecast, low, high}] (periods between the end of the history and the horizon, the one in progress included), points: [{period, forecast, low, high}], model}}`.
  - **Artifact** holds everything `EventTranslator` requires (`sql`, `columns`, `rows`, `truncated`, `ms`, `what`, `why`), plus a `forecast` key: the chart payload with `time_column`/`value_column`.
- **On `ForecastInputError` / `ForecastEngineError`:** content is `{"error": {code, message, fixable}}`, and the artifact is `{"error", "at": "forecast", "sql", "what", "why"}`.
- **Registration:** `make_tools(connector, catalog, with_memory, *, forecaster=None, today=None)` adds the forecast tool only when `forecaster` is set. The keyword default keeps `test_tools.py:243-246` working.

### 7. Agent wiring

- **`app/agent/graph.py` `build_agent`:** `forecaster = get_forecaster()`, passed to `make_tools` with `today`. `capability=capability(forecasting=forecaster is not None)`.
- **`app/services/runs.py` `EventTranslator`:**
  - `_for_model` sets `outcome.tool = "forecast"` when a tool call names `forecast_series`, otherwise `"sql"`. The stage list is unchanged, because the forecast tool really does generate SQL, guard it and execute it.
  - `_rows` becomes `chart = forecast_chart(result["forecast"]) if "forecast" in result else infer_chart(...)`. It also assigns `outcome.chart = chart` unconditionally. The frontend clears the chart on every `sql` event, so a query after a forecast must clear the saved chart too; otherwise saved and live runs differ.
- **`app/agent/middleware.py` `_harvest`:** only artifacts with `at in ("guard", "database")` become pending corrections. Otherwise an `insufficient_history` refusal followed by a successful query gets stored as a "correction". `_prior_fix` would then tell the model later that valid SQL "was refused before".

### 8. Charts and schemas: `app/services/charts.py`, `app/api/schemas.py`

- **`forecast_chart(payload)`** returns `{"type": "forecast", "x": time_column, "y": [value_column], "forecast": {"grain", "interval", "history": [[label, value], …], "points": [[label, mean, low, high], …]}}`. History is trimmed to the last `max(MAX_POINTS - horizon, MIN_HISTORY)` points.
- **Schemas:**
  - `ChartSpec.type` becomes `Literal["bar", "line", "forecast"]`, with `forecast: ForecastChart | None = None`.
  - `TraceAttempt.at` gains `"forecast"`.
  - No migration: `Run.tool` is `String(20)`, and `chart`/`trace` are JSON columns.
- **Contract:** the SSE change is additive, with no new event and no new stage, under the same rules `chart` and `rejected` were added by.

### 9. Prompts: `app/agent/prompts.py` (rule 6: evals before/after)

- **`capability(forecasting: bool) -> str`** is the single place that composes `SQL_CAPABILITY` with `FORECAST_CAPABILITY` or `FORECAST_OFF`. `build_agent` and `evals/recorded.py` both use it.
- **`FORECAST_CAPABILITY`** tells the model:
  - **When:** questions about the future (forecast, predict, estimate, project, next week/month/quarter/year, tomorrow) go to the forecast tool. Anything already in the data stays with the query tool.
  - **Call it on its own**, never alongside another tool call in the same turn. `EventTranslator` records one attempt per model message.
  - **SQL shape:** one row per period, the period start cast to a date, and the measure grouped to the question's grain, newest first. Don't invent empty periods.
  - **`kind`:** `total` for sums and counts (sales, revenue, units, visits, consumption); `level` for readings (price, balance, stock on hand, temperature).
  - **`horizon`** counts periods of the grain: next six months = 6 at month grain; tomorrow = 1 at day grain; next quarter = 3 at month grain.
  - **Its points are figures a tool returned.** State them as a forecast, with the range, the history they rest on and when it ends. Never extrapolate a figure yourself. Don't list every period, because the forecast table shows them: give the next period, the horizon's total or endpoint, and the range, within the existing sentence limits.
  - **`fixable: false`** means explain in plain words and don't retry.
- **`FORECAST_OFF`** (production today): "Forecasting is not available on this service. When asked to predict a future figure, say so in one sentence, don't work out a projection yourself, and offer the history that bears on it."
- **New tool text:** `FORECAST_TOOL_DESC`, which refers to the tables in the query tool's description rather than repeating the schema, and `FORECAST_*_ARG`.
- **`evals/recorded.py`:**
  - `prompt_sha()` hashes `capability(forecasting=False)` in place of the hardcoded `SQL_CAPABILITY`, plus `QUERY_TOOL_*`. It follows its own docstring: hash what the model sees.
  - Replay covers the forecasting-off path, which is the production prompt. `golden_forecast` runs live only, because the forecast numbers feed later request hashes.
  - The existing `golden_sql`/`golden_file` cassettes (already stale per STATUS) are re-recorded once with forecasting off.

### 10. Dependencies: `pyproject.toml`

- New optional extra `forecast = ["timesfm[torch]==2.0.2"]`.
- `numpy` becomes a direct dependency.
- Regenerate `requirements.lock` with `pip-compile --extra dev` (rule 8). The forecast extra stays out of the lock and out of the free Render build.
- New pytest marker `forecast`.
- Locally: `pip install -e ".[forecast]"` with `HF_HOME=D:\hf-cache`, because C: has no free space.

## Frontend (same PR, per the frozen-contract rule)

- **Types:**
  - `lib/api/types.ts`: `ChartSpec` gains `"forecast"` and an optional `forecast: {grain, interval, history: [string, number][], points: [string, number, number, number][]}`. `Attempt.at` gains `"forecast"`.
  - `features/ask/run-types.ts:30`: the `rejected.at` union gains `"forecast"`.
  - There is no zod validation of SSE events or `RunDetail`; they are casts. So nothing else rejects the new shape.
- **`features/ask/chart.ts`:** a `type: "forecast"` branch comes before the `rows.length === 0` check and builds from the spec alone:
  - categories are history labels followed by forecast labels;
  - series "actual" (null across the forecast) and "forecast", which starts at the last actual point so `runs()` draws it connected;
  - `PlottableChart` gains `band: ({lo, hi} | null)[]` and `split`;
  - the domain stays anchored at zero.
- **`components/ask/result-chart.tsx` `Line`:**
  - a band polygon in `fill-series-3` at low opacity;
  - the forecast line dashed in `stroke-series-2`, actuals in `stroke-series-1`;
  - a divider at `split` in `stroke-line-strong`;
  - x labels at start, split and end;
  - legend: actual / forecast / 80% range;
  - existing `globals.css` tokens only.
- **`components/ask/ask-workspace.tsx`:** for a forecast chart, render its points through the existing `ResultTable` (period, forecast, low, high) between the chart and the history table.
- **Run-process labels** (`features/ask/run-process.ts:52`, `components/ask/run-process.tsx:29-31, 93`):
  - `at="forecast"` reads "Couldn't forecast: …", not a read-only-check rejection.
  - The tool shows as `forecast_series` both live and saved. Live runs infer it from `chart.type === "forecast"` or `at === "forecast"`; saved runs map `tool: "forecast"`.

## Tests (TDD; unit tests mock the model)

- **`tests/unit/test_forecast_preprocessing.py`:**
  - date objects;
  - ISO strings with mixed offsets across DST (the MCP shape), which must not raise, and keep wall-clock month buckets;
  - Decimal and numeric strings;
  - unsorted input;
  - duplicates summed vs averaged;
  - null values treated as gaps;
  - zero-fill vs interpolation;
  - current partial period dropped;
  - Monday weeks;
  - one test per error code.
- **`tests/unit/test_forecast_service.py`**, with a `FakeEngine`:
  - context trimmed to `max_context`;
  - horizon bounds;
  - future labels roll over year and quarter correctly;
  - NaN output and engine exceptions become `ForecastEngineError`;
  - outputs are plain Python types;
  - `load_forecaster` builds once, and does nothing when off.
- **`tests/unit/test_tools.py`:**
  - success content and artifact shape;
  - guard rejection identical to the query tool;
  - more than `max_rows` rows newest first is accepted and capped; oldest first gives `wrong_order`;
  - input errors give `at="forecast"`;
  - the tool is absent when the forecaster is None.
- **`tests/unit/test_agent.py`:**
  - `FakeToolModel` → `forecast_series` gives `sql → rows → chart{type:"forecast"} → token`, with `outcome.tool == "forecast"`;
  - a later query clears the saved chart;
  - with forecasting off, the prompt carries `FORECAST_OFF`.
- **`test_middleware.py`:** a forecast refusal followed by success records no correction.
- **`test_charts.py` / `test_schemas.py`:** history trimming; a forecast `ChartSpec` validates; `at="forecast"`.
- **`tests/forecast/test_timesfm_engine.py`** (marker `forecast`, `importorskip("timesfm")`):
  - real checkpoint on a synthetic seasonal series;
  - checks shapes and `lower ≤ mean ≤ upper`;
  - checks it beats seasonal-naive MAE.
  - It is deliberately **not** marked `integration`, because that fixture wipes the local `analyst` DB.
- **Frontend:** `chart.test.ts` covers forecast categories, split, band alignment and connection. `run-machine.test.ts` covers the forecast chart and `rejected.at = "forecast"`. The run-process tests cover the forecast labels.
- **Evals:**
  - New fixture `evals/fixtures/monthly_revenue.csv`: 36 deterministic months, trend plus seasonality, `YYYY-MM-DD` month-start dates ending 2026-08-01, with `revenue_inr` and `units`. A bare `2026-08` would be ingested as text by `duckdb.py:120`.
  - New suite `evals/golden_forecast.yaml`, run live with forecasting on. Every forecast case also carries `expect_type: rows`, because `_primary` requires one:
    - "Forecast revenue for the next six months." → `expect_chart: forecast`
    - "Predict next month's revenue." → `expect_chart: forecast`
    - "Estimate units for the next quarter." → `expect_chart: forecast`
    - "What was the revenue in March 2026?" → `expect_value`, a history question that must stay SQL
    - "Show revenue by month." → `expect_chart: line`
  - `golden_sql.yaml` (rule 6) gains a case valid in both modes: a history question worded with trend words, "How has battery revenue moved month by month?" → `expect_type: rows`. It guards against the forecast tool taking over history questions. There is no `expect_chart`: Postgres dates arrive through MCP as strings, so `infer_chart` draws a bar there.

## Verification

1. `pytest -m "not integration and not forecast"`, plus frontend `pnpm test`, lint and typecheck. All green.
2. **Engine, locally:**
   - First check free commit memory (`FreeVirtualMemory`).
   - Then `pip install -e ".[forecast]"`, `$env:HF_HOME="D:\hf-cache"`, `pytest -m forecast`.
   - Record load time, RSS and latency per forecast, so the 1.1–1.3 GB estimate becomes a measurement in STATUS.
3. **End to end:**
   - Start the MCP server, then the API with `FORECAST_ENGINE=timesfm` and `OPENBLAS_NUM_THREADS=1`, each via `Start-Process powershell -NoExit` so Claude Code's memory-pressure reaping can't kill them.
   - Upload `monthly_revenue.csv`.
   - Ask "Forecast revenue for the next six months". Check the dashed forecast, the band, the divider and the forecast table, and that the answer states a forecast with its range and history.
   - A history question still uses `query_database`.
   - Ask something with too little history (`sales.csv`, 3 months) and check that the answer explains it rather than retrying.
4. **Rule 6 gate:** live before/after for `golden_file`, `golden_sql` and `golden_pdf`, measured twice:
   - with `FORECAST_ENGINE=off` (production);
   - with `timesfm`.

   Plus `golden_forecast` with it on. No suite may drop. Record in `docs/STATUS.md`. Re-record the off-path cassettes.
5. **Docs:**
   - `docs/CLAUDE.md`: the SSE table (chart `forecast`, `rejected.at` forecast) and the architecture list (`app/forecasting/`).
   - `docs/STATUS.md`: a new section with measurements, eval numbers and the production switch-on list.
   - `DEVELOPMENT.md`: enabling it locally.

## Turning it on in production (documented, not done)

- A 2 GB Render instance or larger.
- torch from the CPU index (`https://download.pytorch.org/whl/cpu`) so Linux doesn't pull CUDA wheels.
- The checkpoint downloaded in the build command into a directory inside the project, so it isn't fetched on every start.
- `FORECAST_ENGINE=timesfm`.

## Order of work (after approval)

1. Save this design as the spec at `docs/superpowers/specs/2026-09-22-timesfm-forecasting-design.md` and break it into a step-by-step implementation plan.
2. Build `app/forecasting/` (preprocessing, service, engine) test-first.
3. Build the tool, wiring, middleware fix, prompts and schemas.
4. Build the frontend chart, table and labels.
5. Add the fixture and evals, run the gate, re-record cassettes, update the docs.

Commits: `feat(agent): …`, `feat(web): …`, `docs(status): …`.

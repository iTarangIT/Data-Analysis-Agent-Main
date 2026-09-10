# STATUS

Source of truth for the active phase. Phase N+1 does not begin until phase N's line reads
**done**. Update this file as the last step of every task.

| Phase | Deliverable | Done when | State | Date |
|---|---|---|---|---|
| 0 | repos, Compose, stub graph, SSE endpoint | `curl -N /runs` streams a stub, trace in LangSmith | **done**, tracing dormant | 2026-09-10 |
| 1 | SQL tool on our own IoT DB, guard, evals | `evals/run_evals.py` >= 25/30 | code complete, **gate paused** | 2026-09-10 |
| 2 | JWT auth, vault, `/connections`, then frontend Part B | second person connects a DB without help | not started | — |
| 3 | web tool (Playwright) | Intellicar live query works for two tenants with separate sessions | not started | — |
| 4 | Redis workers, limits, usage, Docker deploy | killing a worker mid-run gives a clean `error` event | not started | — |
| 5 | file tool (DuckDB), charts | spreadsheet-only customer gets value | not started | — |
| 6 | billing | paid plan sets `daily_token_budget` | not started | — |

## Verified

Local infrastructure is up. Native Postgres 17 on 5432 holds all three databases.

- `analyst` carries `alembic_version`, `tenants`, `connections`, `runs` at revision
  `8c6d70bc2934`. `checkpoints` carries the four LangGraph tables.
- `demo` is seeded: 240 telemetry rows, and a range-partitioned `readings` table with two
  children that exists to prove the connector hides partitions.
- `GET /health` returns `{"status":"ok"}`; `/openapi.json` exposes `/health`, `/connections`
  and `/runs`, which is what `pnpm gen:agent` consumes in phase 2.
- `POST /runs` returns 401 without a bearer token and streamed `status` -> `token` -> `done`.
- Structured logs carry `tenant_id` and `run_id` on every line of a run.
- Customer data is read-only at all three layers on the demo source. Five different write
  statements were refused by the database itself, bypassing the guard entirely.
- **99 tests pass, 2 skipped** (both need a model key). Lint clean. Coverage: `sql_guard.py`
  100%, `app/security/` 100%, `connectors/postgres.py` 94%, overall 83%. Floors are 85/85/70.

### The iTarang IoT schema

Reached over the SSH tunnel on `127.0.0.1:5500`. PostgreSQL 16.14, database `itarang`.

It has 115 tables in `public`, of which 100 are weekly partitions and 242 relations carry
`relispartition`. `Inspector.get_table_names` returns all of them, so `describe_schema` now
filters on the catalog flag rather than a name pattern, leaving **15 business tables and 129
columns**: `vehicles`, `vehicle_state`, `trips`, `users`, `alerts`, five `telemetry_*` tables,
`distance_rollup`, `daily_distance_per_vehicle`, `hourly_battery_per_vehicle`,
`aggregator_runs`, and two `dashboard_*` tables.

Sample rows are off (`SCHEMA_SAMPLE_ROWS=0`). Eight of the 15 tables carry identifier-like
columns, including GPS coordinates, vehicle `owner`, `username` and `loan_application_id`, and
samples would have put those in every generation prompt while growing it from 6KB to 30KB.

## The IoT data, as measured on 2026-09-10

`analyst_ro` exists on `itarang` and is verified read-only: DELETE, UPDATE, INSERT and CREATE
were each refused by the database itself, with reads still working. The DSN is `IOT_RO_DSN`
in `.env` (the `@` in the password is percent-encoded).

Only 5 of the 15 tables carry data that can answer a question today.

| Table | Rows | Data through | Usable |
|---|---|---|---|
| `vehicles` | 362 | current | yes, but `makemodel` is 100% NULL |
| `vehicle_state` | 361 | current | yes, the richest table |
| `alerts` | ~398,000 | 2026-10-10 | yes, though 1 `alert_type` and 1 `severity` only |
| `distance_rollup` | ~33,000 | 2026-10-10 | yes |
| `users` | 2 | current | trivially |
| `telemetry_battery` | ~45,900,000 | **2026-07-01** | stale by 10 weeks, and too slow |
| `telemetry_gps` | ~10,000,000 | **2026-07-05** | stale by 9 weeks, and too slow |
| `telemetry_can` | ~8,100,000 | **2026-07-02** | one day of data only |
| `trips` | 0 | — | empty |
| `telemetry_fuel` | 0 | — | empty |
| `daily_distance_per_vehicle` | 0 | — | empty |
| `hourly_battery_per_vehicle` | 0 | — | empty |
| `dashboard_nbfc_loans_with_iot` | 0 | — | empty |
| `dashboard_vehicle_monthly_range` | 0 | — | empty |
| `aggregator_runs` | 0 | — | empty |

Two separate problems, both measured rather than assumed:

1. **The telemetry pipeline appears to have stopped in early July.** The newest
   `telemetry_battery` partition ends 2026-07-01 and the newest `telemetry_gps` ends
   2026-07-05, while `alerts` and `distance_rollup` have partitions running to 2026-10-10.
2. **Fleet-wide telemetry aggregates cannot finish inside the 8s role timeout.** The only
   index is `(vehicleno, time)`, so a time-range filter without a vehicle cannot use it.
   `select avg(soc_pct) from telemetry_battery` timed out, and so did the same query narrowed
   to one day. `alerts` grouped over 7 days returned in 0.29s.

## Phase 1 gate: paused by decision

Apoorv chose to fix the IoT data pipeline before writing the 30 golden cases, rather than
scope them to the four usable tables. The agent code is complete and tested; only the eval
gate waits. It can resume once telemetry is backfilled and the empty tables are populated.

### Outstanding obligation under hard rule 6

`SQL_SYSTEM` in `app/agent/prompts.py` gained guidance about statement timeouts, time-range
constraints, rollup tables and entity-first indexes, written tenant-neutrally because that file
serves every customer. Hard rule 6 requires evals to be run and a before/after pass rate
reported for any prompt change. **That has not been done**, because no `OPENROUTER_API_KEY` is
configured and the gate is paused. Run the evals and record both rates before this prompt
change is considered merged.

## The agent: create_agent, per the LangChain v1 documentation

Apoorv asked to follow the official documentation and go all-in on `create_agent`, so the
hand-written LangGraph state machine is gone.

- `app/agent/tools.py` defines `query_database` with the `@tool` decorator from
  `langchain.tools`, with a custom name, an explicit description and a Pydantic `args_schema`.
  It uses `response_format="content_and_artifact"`: the model reads a 50-row preview while the
  full result travels as the artifact, so a 500-row answer never enters the model's context.
- `app/agent/graph.py` builds the harness with `langchain.agents.create_agent`, passing the
  model, the tool list, the system prompt and the checkpointer.
- `router.py`, `sql_gen.py`, `db_exec.py`, `answer.py` and `state.py` are deleted. The model
  now decides whether a question needs a tool, which is what the router used to do, and
  `create_agent` supplies the loop that the retry edges used to.
- `sql_guard.py` stays exactly where it was and is now called from inside the tool. A tool is
  invoked by the model and cannot assume anything guarded first, so this is the only remaining
  place the guarantee lives, and it is tested from both the unit and integration suites.

### The frozen SSE contract still holds

`create_agent` has two nodes, `model` and `tools`, but the contract names five stages, so
`EventTranslator` in `app/services/runs.py` reports each step as the stage it actually
performs: the first model call is the routing decision, a model call carrying a tool call is
generation, and the tool guards then executes. An integration test asserts the exact sequence
`router, sql_gen, sql_guard, db_exec, answer` and the exact event order, so `analyst-web`
needs no change in phase 2.

A rejected query emits `sql_guard` and then nothing else, so no `sql` or `rows` event ever
reports a statement that did not run. That is asserted too.

### Verified without a model key

A scripted `FakeMessagesListChatModel` drives the real HTTP route against the demo database,
covering auth, `prepare_run`, the agent loop, the tool, the guard, SSE encoding and the `Run`
row. A second test scripts the model into attempting `delete from dealers` and asserts the
statement never reaches the database and is never reported as executed SQL.

98 tests pass, 2 skipped. Coverage: overall 95%, `sql_guard.py` 100%, `app/security/` 100%,
`services/runs.py` 96%. Floors are 85/85/70.

`DEVELOPMENT.md` and `CLAUDE.md` were updated in the same change, because both described the
five-node graph that no longer exists.

## Open checks

| # | Blocked on | Unblocks |
|---|---|---|
| 1 | `OPENROUTER_API_KEY` | every model call: the SQL path, the 2 skipped tests, the eval gate |
| 2 | `analyst_ro` on `itarang` | registering the IoT connection at all |
| 3 | `LANGSMITH_API_KEY` | the "trace in LangSmith" half of phase 0's done-line |
| 4 | items 1 and 2 | writing the 30 golden cases against the real schema |

### 4. The IoT eval target

The IoT database is reached over an SSH tunnel published on a local port; the endpoint and
credentials live in `.env`, which is git-ignored, and are not recorded here. The port in
`.env` was initially wrong and has been corrected.

The account originally supplied was read-write. Hard rule 4 requires the role layer to be
read-only independently of the connector and the guard, so `scripts/create_readonly_role.sql`
was run against `itarang` and the agent uses the resulting `analyst_ro` DSN, held in
`.env` as `IOT_RO_DSN`. Writes through that role are refused by the database itself; see the
verification below.

`describe_schema()` originally sampled every table in `public`, and that becomes the SQL
generator's prompt. On this schema that meant 115 tables, so the connector now filters
partition children and sample rows are disabled.

The four cases now in `evals/golden_sql.yaml` target the `demo` fixture and exist only so the
harness is testable; they are replaced by 30 cases generated from the IoT schema.

## Deviations from the manual, recorded deliberately

1. **`testcontainers` is not a dependency.** Local development runs on native Postgres with no
   Docker (hard rule 5a), so integration tests target the local server. `pyyaml` was added
   because `evals/run_evals.py` imports it and the manual never declares it.
2. **The guard treats CTE and subquery aliases as local names.** Verified against sqlglot 30:
   `WITH recent AS (...) SELECT * FROM recent` resolves `recent` as a table, so the manual's
   guard rejects every CTE the generator writes.
3. **The guard rejects `SELECT ... INTO`.** It parses as an ordinary `Select` but creates a
   table, and the manual's forbidden list misses it.
4. **The guard accepts any `SetOperation`, not just `Union`,** and caps a non-literal `LIMIT`
   rather than trusting it. A subquery limit raised `TypeError` in the manual's version.
5. **`sql_gen` uses a Pydantic output schema** instead of stripping code fences off the model's
   reply, which hard rule 1 forbids.
6. **The budget and connection checks moved out of the stream** into `prepare_run`. Raising
   `BudgetExceeded` inside the SSE generator, as the manual does, cannot produce a 429 because
   the status line has already been sent.
7. **`schema_cached_at` is null-checked** before being used in a subtraction.

Two manual simplifications are kept and flagged rather than fixed. `graph.stream` is synchronous
inside an async generator and holds the event loop for the length of a run; it moves to an `arq`
worker in phase 4. And `answer` emits one `token` event carrying the whole answer rather than
per-chunk streaming, which the frozen SSE contract permits.

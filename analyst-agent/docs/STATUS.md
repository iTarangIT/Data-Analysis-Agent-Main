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

### Outstanding obligation under hard rule 6, corrected 2026-09-10

This entry named `SQL_SYSTEM` and asked for a before/after pass rate on the statement-timeout
and rollup guidance. Two things about it were wrong, and a third makes the measurement it asks
for worthless where it can actually be run.

1. **The symbol is gone.** `SQL_SYSTEM` was deleted with the five-node graph in `8ac6e69`. The
   guidance now lives in the "Writing SQL" block of `AGENT_SYSTEM`, the only prompt left.
2. **There is no "before" in git.** `git log -- app/agent/prompts.py` has three commits, and the
   timeout and rollup lines are already present in the first of them, `c6fc6a0`. The only
   pre-change text is the manual's §7.2, which belongs to an architecture that no longer exists.
   There is no like-for-like earlier prompt to record.
3. **An A/B on `demo` would measure nothing.** The guidance says a query that scans a whole
   table will be killed, so prefer a rollup. The largest table in the demo fixture is
   `telemetry` at 240 rows. Nothing there can time out, so the instruction is inert and the
   result would read 4/4 against 4/4. Publishing that would satisfy the rule on paper while
   proving nothing, and would close an item that is not closed.

The guidance is about an 8s timeout against 45.9M rows with only a `(vehicleno, time)` index.
It can only be evaluated against the IoT database, which is exactly what the phase 1 gate is
paused on.

**The obligation stands and is now scheduled rather than blocked.** `evals/recorded.py` makes
the eventual A/B two commands: record a cassette with the timeout bullet removed, record another
with it present, replay both. Until the telemetry backfill lands there is nothing honest to
report, and this entry stays open.

## Phases 3 to 5 begin with phases 1 and 2 still open, by decision

`DEVELOPMENT.md` §2 and the table at the top of this file both say phase N+1 does not begin
until phase N's line reads done. Apoorv asked for the remaining backend anyway, and confirmed
after the conflict was raised under §9. Recorded here rather than left implicit.

What is actually outstanding in the two open phases is not backend code. Phase 1 waits on the
IoT data, and phase 2's done-line, "second person connects a DB without help", is a frontend
milestone: the backend half of phase 2, tenant JWTs, the vault and `/connections`, shipped in
phase 0 and 1 commits. `analyst-web` does not exist yet.

Phase 6, billing, is deferred. Docker is cut from phase 4; see that phase's section.

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

## Model provider: Gemini

`OPENROUTER_API_KEY` was replaced with `GEMINI_API_KEY`, so `app/llm.py` now builds
`ChatGoogleGenerativeAI` and `langchain-google-genai` replaces `langchain-openai`.

`gemini-2.5-flash` is refused for new keys ("no longer available to new users"); the API
itself recommends `gemini-3.6-flash`, which is the default.

### Running it live found four defects the fake model could not

1. **`Decimal` is not JSON serialisable.** Any NUMERIC, DATE, TIMESTAMP or UUID column killed
   the SSE stream mid-flight, and the client saw a truncated body. `json.dumps` at the SSE
   boundary now uses `default=str`, which is lossless; `float()` would lose precision on money.
   The eval harness accepts numeric strings for the same reason.
2. **Gemini 3 returns content blocks, not a string.** `str(message.content)` would have put a
   Python list repr into the `token` event. The translator reads `message.text`, which
   flattens both shapes.
3. **The recursion limit was derived from `max_sql_retries`,** which measures retries after a
   rejection, not total tool calls. A model that legitimately queried three times was cut off
   with `GraphRecursionError`. `max_tool_calls` (default 6) is now its own setting, and
   exhaustion returns a clear message instead of "run failed; see logs".
4. **The eval harness reused thread ids** like `eval-0`. The checkpointer keeps chat memory per
   thread, so a later run answered from the previous run's conversation without querying at
   all. Each invocation now stamps its threads uniquely.

### Verified live, end to end

`curl -N /runs` against the demo database streamed the full contract in order, with correct
SQL (a `GROUP BY` with `ORDER BY` and `LIMIT`), correct rows, and an accurate answer. One run
took 40 seconds.

### The free tier blocks the phase 1 gate

The key is on the free tier: **20 requests per day, per model**
(`GenerateRequestsPerDayPerProjectPerModel-FreeTier`). One eval case costs two or more model
calls, so the 30-question gate needs 60 to 90, and today's allowance was exhausted after a
handful of runs. The quota is per model, so `gemini-3.1-flash-lite` and `gemini-3.5-flash-lite`
each have their own allowance, but 20 a day is not workable either.

The eval run before the quota ran out scored 1 of 4, and that number is not trustworthy: it was
taken while defects 3 and 4 were still present. There is still no honest before/after pass rate
for the prompt changes, so the hard rule 6 obligation below stands.

## Model comparison, measured 2026-09-10

Three questions against the demo database, run directly rather than over HTTP.

| Model | Latency | Correct |
|---|---|---|
| `gemini-3.6-flash` | ~40s (one sample) | not re-measured, quota exhausted |
| `gemini-3.1-flash-lite` | 4.9 to 7.1s | 2 of 3 |
| `gemini-3.5-flash-lite` | 1.9 to 2.0s | 2 of 3 |

`gemini-3.5-flash-lite` is roughly twenty times faster than `gemini-3.6-flash` with no loss of
correctness on these cases, so it is now the default. **This needs re-checking against the IoT
schema**, which is far harder than the three-table demo fixture: 15 tables, weekly partitions
and an 8s statement timeout. Three easy questions are thin evidence for a model choice.

The third case failed on both models and was a defect in the case, not the models. "Which city
has the most batteries sold?" has no unique answer: Gurugram and Nashik both have 2, so a model
answering Gurugram was marked wrong for being right. It is replaced with an unambiguous
question, and `golden_sql.yaml` now warns to check every new case for ties. That matters for
the 30 IoT cases.

## Open checks

Items 1 and 2 below were closed on 2026-09-10 and are kept for the record.

| # | Blocked on | Unblocks | State |
|---|---|---|---|
| 1 | ~~`OPENROUTER_API_KEY`~~ `GEMINI_API_KEY` | every model call | **closed**, key configured |
| 2 | `analyst_ro` on `itarang` | registering the IoT connection | **closed**, role created |
| 3 | `LANGSMITH_API_KEY` | the "trace in LangSmith" half of phase 0's done-line | open |
| 4 | the telemetry backfill | writing the 30 golden cases against real data | open |

Item 4 was "blocked on items 1 and 2". Both are closed and it is still blocked, because the
real obstacle was never the key or the role: 7 of the 15 IoT tables are empty and the telemetry
pipeline stopped in early July. Cases written against that today would encode the outage.

The **20 requests per day per model** free-tier limit no longer blocks the harness itself.
`evals/recorded.py` records once and replays offline, so everything downstream of the model is
gated for free. It does not gate a prompt change; see the hard rule 6 entry above.

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

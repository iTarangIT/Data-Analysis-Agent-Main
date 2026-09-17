# STATUS

Source of truth for the active phase. Phase N+1 does not begin until phase N's line reads
**done**. Update this file as the last step of every task.

| Phase | Deliverable | Done when | State | Date |
|---|---|---|---|---|
| 0 | repos, Compose, stub graph, SSE endpoint | `curl -N /runs` streams a stub, trace in LangSmith | **done**, tracing dormant | 2026-09-10 |
| 1 | SQL tool on our own IoT DB, guard, evals | `evals/run_evals.py` >= 25/30 | code complete, **gate paused** | 2026-09-10 |
| 2 | JWT auth, vault, `/connections`, then frontend Part B | second person connects a DB without help | **in progress** | backend auth, history and delete shipped 2026-09-11; identity moved to Supabase with Google 2026-09-17; frontend building |
| 3 | ~~web tool (Playwright)~~ | — | **removed** by decision; `3203026` reverts to bring it back | 2026-09-15 |
| 4 | Redis workers, limits, usage, ~~Docker deploy~~ | killing a worker mid-run gives a clean `error` event | **done**, verified live, Docker cut | 2026-09-11 |
| 5 | file tool (DuckDB), charts | spreadsheet-only customer gets value | **done** | 2026-09-10 |
| 6 | billing | paid plan sets `daily_token_budget` | deferred by decision | — |

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

## Phases 3 to 5, built 2026-09-10

265 tests pass, 6 skip (2 need a model key, 4 need Intellicar). Lint clean. Coverage 91% overall
against a 70% floor; `sql_guard.py` and `app/security/` are both at 100% against an 85% floor.

Evals were run at every step that touched the guard or a prompt: 4/4 before and 4/4 after, every
time, replayed from a cassette with no drift reported. A new seven-case file suite records and
replays 7/7.

### Phase 3, the web tool: done, verified live on 2026-09-11

`kind="web"` was accepted by the API from phase 2 but `connector_for` raised for it, so a web
connection could be created and then failed as a 500 on the first run. That is closed.

**The done-line passes against the real dashboard.** Two tenants, two session files in two
tenant directories, six cookies each, byte-different from one another, and neither containing
the plaintext password. Byte-different is the part that matters: it is what distinguishes two
independent sessions from one shared cookie jar copied twice.

To re-run it, export the four variables and run that one file. `MSYS_NO_PATHCONV=1` matters in
Git Bash, which otherwise rewrites the leading slash of the match string into a Windows path and
produces a confusing "no dashboard data matched 'C:/Program Files/Git/api/...'":

```bash
export MSYS_NO_PATHCONV=1 PLAYWRIGHT_BROWSERS_PATH="D:\ms-playwright"
export INTELLICAR_URL=... INTELLICAR_ID=... INTELLICAR_PASSWORD=...
export INTELLICAR_DATA_MATCH=/api/group/listevgroups
pytest tests/integration/test_web_runs.py
```

It drives a scripted model, so the check costs no model quota; only the dashboard has to be real.

**The sign-in was a guess, and the guess was wrong in every particular.** The original code
filled a username and password on the page. The real dashboard has no inline form: it has one
button, which opens a popup to a separate single sign-on host, which asks for an identifier,
then for a password on a second screen, then closes itself.

The closing is the mechanism, not a detail. The popup hands a token back to the window that
opened it, so driving the sign-in URL directly mints a valid token that nothing consumes. The
popup must be opened from the dashboard. A rejected credential leaves it open, which is exactly
how the two failure paths are told apart.

The old code could never have worked, and the tests passed anyway, because the fake driver
modelled the guess rather than the site. That is the lesson worth keeping from this phase: a
fake built from an assumption tests the assumption.

**A race only visible against the real site.** After the token goes back, the dashboard reloads
itself. Issuing a reload at that same moment killed it with `ERR_ABORTED`. The code now waits for
the dashboard's own reload and navigates only if none arrives.

**Two timeouts were guesses too.** Navigation was 30s against a page that loads Google Maps,
Firebase and reCAPTCHA before it is interactive, and it timed out repeatedly; it is 60s. Waiting
for data was a fixed 1.5s sleep, too short here and wasteful on a fast dashboard, so it polls up
to `WEB_DATA_TIMEOUT_MS` and stops the moment the data lands.

**The dashboard slows under repeated sign-ins.** Running the whole file back to back, the first
test fails on a navigation timeout while the rest pass, and it recovers after a few minutes'
pause. Production does not behave like this: the tests wipe the session store before each test
and so force a fresh login every time, which is the worst case by construction. A real tenant
signs in once and reuses the session until it expires. Re-run the file on its own, not in a loop.

**`INTELLICAR_DATA_MATCH` must name one endpoint.** The dashboard calls about ten. The vehicle
groups are at `/api/group/listevgroups`; a broad `/api/` match captures whichever happens to land
last, which is not stable across loads. Every Intellicar endpoint returns
`{"status", "data": [...], "err", "msg"}`, which the existing unwrapping already handled.

The manual's 7.7 builds a graph node for the five-node architecture that no longer exists, so the
capability is a `@tool` like every other one. It takes no arguments: a dashboard has one payload
and no query language.

**Playwright's sync API refuses to start on a thread that has a running event loop**, and the
tool is called from inside `agent.stream`, which runs on one. So the browser runs on a worker
thread, with the contextvars context copied across so its log lines keep `tenant_id` and
`run_id`. A test calls the fetch from inside a running loop and fails without the hop. This
survives the queue, because arq is asyncio too.

`prepare_run` is async now and refreshes the schema through `asyncio.to_thread`.

A web connection is deliberately not smoke-tested at creation: a browser launch would make that
the most expensive endpoint in the service, and a wrong password still surfaces as a real 400
from the first run, because `prepare_run` happens before the stream opens.

### Phase 4, the queue: done, minus Docker

Apoorv cut deployment. There is no Dockerfile, no production compose file, no Caddyfile and no
container CI, and none is planned until there is a VPS. `docker-compose.dev.yml` is untouched.
Manual section 9 is unimplemented; when it returns, the line that matters most is
`flush_interval -1` in the Caddyfile, without which Caddy buffers the SSE stream and the chat UI
shows nothing until a run ends.

**The done-line passes against a real worker**, as of 2026-09-11. Memurai Developer 4.1.2 is
installed and the check is one command:

```powershell
python scripts/check_killed_worker.py
```

It starts a real uvicorn and a real arq worker, opens the SSE stream, kills the worker mid-run,
and asserts the stream ends with exactly one `error` event and the run row is not left
`running`. Twice in a row: frames already published still arrive, then
`error: the run stopped responding`, and the row reads `error` / `worker lost`.

**Running this for the first time found the queue path completely broken against real Redis**,
which is recorded under the bugs below. It is the single strongest argument in this project for
doing the manual end-to-end checks rather than trusting a green suite.

**Ctrl-C will not do**, and this is a trap worth remembering: `loop.add_signal_handler` is
unsupported on Windows, so arq registers no handler and its shutdown waits for the running task.
Ctrl-C would let the run finish and the check would falsely pass. The script kills by pid.

**Two ways the check can pass without testing anything**, both learned the hard way and both
guarded in the script. A single-tool question finishes in under two seconds, faster than a kill
can land, so the question is heavy enough to need several tool calls. And looking the worker up
with PowerShell costs the better part of a second, so it is killed by tracked pid instead.

**Memurai installs only outside winget.** `winget install Memurai.MemuraiDeveloper` fails with
MSI 1603, `SFXCA: Failed to create temp directory. Error code 5`, despite running elevated.
Downloading the MSI and running `msiexec /i` directly succeeds.

**The synchronous-stream deviation is resolved.** `agent.stream` no longer holds the event loop;
`execute_run` runs under `asyncio.to_thread` in both modes. That is true with the queue off as
well, so client disconnects are now observed and keep-alive pings fire. The fix is the threading,
not the queue.

One `sse_frame` builds both the Redis stream entry and the SSE frame, so the two transports
cannot drift into producing different bytes.

### Phase 5, files and charts: done

Uploads become Parquet at ingest, so the Excel extension is never needed and CSV type sniffing
happens once rather than per run. The connector materialises every source as a real table and
*then* sets `enable_external_access=false` and `lock_configuration=true`. Verified against duckdb
1.5.5: after that, `read_csv_auto`, `read_parquet`, `read_text`, `read_blob`, `ATTACH` of a file,
`INSTALL` and `COPY ... TO` all raise, and the flag cannot be turned back on.

`kind="file"` is deliberately **not** accepted on `POST /connections`. A client-supplied path
would be an arbitrary-file-read primitive that no SQL guard could catch, because the path is
inside the connector long before any SQL exists. Uploads go to `POST /connections/file`, where
the server mints every path.

Charts are inferred in code, not asked of the model. Section 16.2 put this in `answer_node`,
which no longer exists, but its trigger was already deterministic. A model call would have cost
half again as many requests against a 20-per-day quota and made charts impossible to gate offline.

## Deviations from the manual, recorded deliberately (continued)

8. **There is no `Usage` table.** Section 5.2 defines only Tenant, Connection and Run and says Run
   is the ledger to price from; `Usage` survives only in a stale directory-tree comment.
9. **`GET /usage` lives in the agent, not analyst-web.** The ownership table says the web app
   reads `runs` aggregates itself, but `runs` is in the agent's App DB, not Supabase. The Next.js
   route will proxy it. `pnpm gen:agent` must be re-run against this surface: it gained
   `/usage`, `/runs/{id}` and `/connections/file`.
10. **Rate limiting is DB-backed, not Redis-backed,** so it behaves identically with the queue
    off. It costs nothing extra: it is a filter clause on the scan the budget check already did.
11. **No `app/agent/nodes/web_tool.py`.** Section 7.7 targets the deleted five-node graph.
12. **The SSE contract gained `chart`** before `analyst-web` existed, so there was no second repo
    to update in the same PR. Additive, no new stage, both doc tables updated.
13. **Reversed 2026-09-17, see "Identity moves to Supabase" below.** **Sign-up and sign-in live in the agent, not the web app.** The ownership table assigned
    identity to Supabase inside analyst-web. Owner's call on 2026-09-11: put identity beside
    the data it protects. The cost is a `users` table, Argon2id and `/auth/*` here; the payoff
    is that the browser never holds a token, the web app never holds the signing secret, and
    `decode_token`, `TenantContext` and every existing route were untouched, because the new
    endpoints mint exactly the claim shape this service already accepted. Hand-minted tokens
    therefore still work everywhere, which is what keeps the eval harness running.
14. **Retired 2026-09-17 with the refresh tokens themselves.** **Refresh tokens are opaque, not JWTs.** `decode_token` accepts any correctly signed token
    carrying `tenant_id` and `sub`, so a JWT refresh token would be accepted as a bearer and
    hand out thirty days of access to the whole API. Adding a `typ` claim would have broken
    every hand-minted token. A random string is not a decodable JWT, so the problem disappears.
    `tests/integration/test_auth_api.py` asserts this, and is what fails if anyone "simplifies"
    it later.
15. **Run history carries no result rows, by design.** `runs` records `rows_returned`, an
    integer, and the grid is discarded when the stream ends. Storing it would put customer rows
    in the App DB permanently, which is exactly what `SCHEMA_SAMPLE_ROWS=0` exists to prevent.
    History shows the question, the SQL and the answer; a past result is re-read by re-running.
16. **Deleting a connection is a soft delete that blanks the credential.** `runs.connection_id`
    has no `ondelete`, so a hard delete fails for any connection ever used, and cascading would
    destroy the ledger we price from. The row survives so history can still name the source,
    but `secret_enc` is emptied, because "delete this connection" has to mean the customer's
    password is gone.

## Bugs found and fixed while doing this

1. **Token accounting was keyed on the configured model name** while `langchain-google-genai`
   reports the resolved one. Any alias or dated variant recorded zero, and `daily_token_budget`
   is enforced from exactly that number, so **the budget was unenforceable** whenever the two
   differed. Tokens are now summed across every reported model, and the reported id is stored.
2. **A disconnected client left its run `running` for ever.** `GeneratorExit` is a
   `BaseException`, so `except Exception` never saw it. Both transports now abandon the run on
   teardown, and a reaper sweeps what a killed process leaves behind. That reaper is
   load-bearing: `max_concurrent_runs` counts running rows.
3. **The guard's rejection for a table function said `tables not allowed: ['']`**, which told the
   model nothing, so it reissued the same query until the tool budget ran out.
4. **Every queued run reported a dead worker**, found the moment Memurai was installed and phase
   4's done-line run for the first time. arq builds its pool with `decode_responses=False` and
   has to, because its own job payloads are pickled bytes. So frames came back bytes-keyed, the
   consumer's `"event" not in fields` test skipped all of them, the stall clock ran out, and a
   run the worker had answered correctly in under two seconds was reported to the customer as a
   worker that died. Silent by construction: nothing raises, frames are just dropped.

   Both fakes were built `decode_responses=True`, so eighteen tests passed against a Redis that
   behaved as the code assumed. They are `False` now; reverting the fix fails seven of them.
   Same shape as phase 3's login fake. **A fake built from an assumption tests the assumption**,
   and that sentence has now cost this project two live bugs.
5. **The shipped `REDIS_URL` default could not work on Windows.** Memurai binds IPv4 only and
   `localhost` resolves to `::1` first, so the client spent its whole connect timeout on IPv6.
   The default is `127.0.0.1` now. `memurai-cli ping` answers normally throughout, which makes
   this present as an application bug rather than a name-resolution one.

## Missing-data handling, built 2026-09-12

The agent had one instruction for an empty result, "say so plainly and suggest one reason", and
no way to tell an empty table from a filter that matched nothing from a period after the data
ends. On this customer's data that is most of the product: 7 of 15 tables hold nothing and
telemetry stopped in early July. The reason it offered was a guess.

**The connector now reports what each table holds.** `describe_schema` carries a row bucket and,
for a time-partitioned table, how far its data runs. `app/connectors/pg_stats.py` is where that
is worked out, and everything in it reads the catalog or stops at one row; nothing scans, because
the tables this matters most for are the ones that cannot be scanned inside the timeout.

Three things about it are load-bearing and were all nearly got wrong:

1. **`reltuples` cannot prove a table is empty.** It is -1 until a table is analysed and 0 for
   one analysed while empty and bulk-loaded since. Measured on the local `demo` database, four
   of five tables read -1. Emptiness is settled by an `EXISTS` probe or reported as unknown.
2. **Summing partition children with `GREATEST(reltuples, 0)` reports a populated table as
   empty.** `readings` holds 3 rows and the sum reads 0, because its children were never
   analysed either. Telling the model a populated table is empty is the exact fabrication this
   work exists to prevent.
3. **The newest partition bound is not where the data ends.** Partitions are created weeks
   ahead, so a pipeline that stopped on 2026-07-02 would advertise coverage to 07-13. Only the
   newest *non-empty* child's bound is reported, and a DEFAULT partition suppresses the claim
   entirely.

**Recency is partition bounds only, never `max(ts)`.** The gate is not just cost. A bound is DDL
the customer's DBA wrote; a `max(ts)` is a value read out of a row and pasted into every prompt
for six hours, which under a strict reading of `SCHEMA_SAMPLE_ROWS=0` is a sample of size one.
Owner's call on 2026-09-12: bounds only. Unpartitioned tables report no coverage date.

**The prompts encode the policy.** The answering block now requires every figure to come from a
returned row, requires an empty result to be explained rather than reported, requires a derived
answer to be called an estimate, and keeps the answer in prose because the client renders one
paragraph with no markdown. `SQL_CAPABILITY` lost the line that read "if the question is not
about the customer's data at all, answer in one sentence without calling a tool", which was the
one place in the service that invited an answer from outside the customer's data.

### Rule 5 of the policy, combining sources: a deviation, recorded

The policy asks for several sources to be consulted and merged. `app/agent/router.py` binds a run
to one source on purpose. That stands; what was added is a one-directional fallback, live to
historic only. An empty database result is answered from related tables inside the same source,
never by putting a historic question to a dashboard that only knows the present moment.

It is done with `create_agent` middleware rather than a second agent run. `app/agent/fallback.py`
registers the database tool with the agent but takes it back out of what the model is shown,
until the dashboard has actually been called and come back empty or broken. That keeps the
router's real objection intact, that the agent cannot offer a source it has no tool for, while
the run stays one stream, one answer, one thread.

A second agent run was the obvious alternative and was rejected after being costed: the first leg
only ends when the model writes an answer, so the customer would watch "the dashboard could not
be read" stream in and then be overwritten, and the second leg would have to resume a thread
holding a `fetch_dashboard` call it had no tool for.

The stage sequence is `router, web_tool, sql_gen, sql_guard, db_exec, answer`. No new stage, no
new event, so the frozen SSE contract is untouched and the frontend needs no change.

`prepare_run` covers the half the middleware cannot: when the dashboard's schema cannot be read
at all the agent does not exist yet, so the run becomes a database run outright and is told to
say so. It still refuses when there is nothing to fall back to.

### Rule 9, confidence: no field, by decision

No `HIGH`/`MEDIUM`/`LOW` column, no badge, no SSE event, no migration. Confidence is carried in
the wording of the answer. This follows the frontend's own rule that only what the data supports
gets drawn, and it is the reason this change touches one repo instead of two.

### Two defects found while building this

1. **`Row.t` is a SQLAlchemy built-in.** The emptiness probe aliased its column `t`, and
   SQLAlchemy exposes `.t` as a synonym for `.tuple()`, so `row.t` returned the whole row and
   every probe result was keyed by a tuple. Silent: the dict was populated, the lookups just
   never matched, and every partitioned table reported no coverage.
2. **Registering a tool with middleware also advertises it.** `wrap_model_call(tools=[...])`
   puts the tool in front of the model from the first turn, which is exactly what the router
   exists to prevent. The middleware now removes it from `request.tools` until the fallback
   fires. A test asserts the model is offered `["fetch_dashboard"]` on the first call and both
   tools on the last; without it the regression is invisible, because a scripted model ignores
   the tool list.

### A pre-existing bug fixed on the way

`app/workers/runs.py` called `connector.describe_schema()` directly, bypassing the six-hour
cache. With the queue on, every run re-introspected: a second full browser sign-in for a web run
whose schema `prepare_run` had just refreshed, and it would have run the new statistics queries
on every run rather than every six hours. It goes through `refresh_schema_cache` now.

### The fixture gained the two shapes being tested for

`scripts/demo_customer.sql` had no empty table and no stale one, so a missing-data eval against
it would have measured nothing, the same trap this file already records for the
statement-timeout guidance. It now seeds an empty `trips` and a `gps_pings` whose data stops on
2026-07-02 with a partition already created ahead of it, and runs `ANALYZE`, without which every
table reports as never analysed and the tool description changes under the eval cassettes the
moment autovacuum catches up. The stray `data` table that survived every reseed is dropped.

### State

433 tests pass, 6 skipped. Lint and format clean. Coverage 70% overall against the 70% floor,
with `sql_guard.py` and `app/security/` still at 100% against theirs. `app/agent/fallback.py` is
at 100%.

**Two things are not done, and neither is optional.**

1. **The demo database has not been reseeded.** `scripts/demo_customer.sql` is written but needs
   the postgres superuser password, so `tests/integration/test_schema_stats.py` has never run.
   Reseed, then run it.
2. **There is no before/after eval pass rate, so hard rule 6 is not satisfied.** The prompt hash
   moved from `de39cc3c` to `8c37188a`, so both cassettes are unfindable and replay fails loudly
   by design. Recording the pair needs a billed `GEMINI_API_KEY`. The baseline must be recorded
   against an untouched tree: the tool description changes three times in this work, and
   `_tools_sha` drifts any cassette taken part-way through.

## Known limits and open checks

| # | Item | Blocked on |
|---|---|---|
| 1 | `LANGSMITH_API_KEY` | the tracing half of phase 0's done-line |
| 2 | The 30 IoT golden cases | the telemetry backfill, unchanged |
| 3 | The hard rule 6 A/B on the IoT prompt | item 2; the harness makes it two commands |
| 4 | Reseeding `demo`, so `test_schema_stats.py` can run at all | the postgres superuser password |
| 5 | The hard rule 6 A/B on the missing-data prompts | a billed `GEMINI_API_KEY`; record the baseline on an untouched tree |

Other things worth knowing rather than fixing:

- **C: has no free space**, which this work did not cause. It broke the Chromium install at 80%
  with `ENOSPC` and later broke writing a log file. Chromium therefore lives under
  `D:\ms-playwright`, and `PLAYWRIGHT_BROWSERS_PATH` must point there. Anything that stages
  through the temp directory needs `TEMP` on D: too.
- **`secret_enc` appears in `/openapi.json`**, which fails the manual's 9.6 grep. It is only the
  word, inside `ConnectionOut`'s docstring explaining that the model has no secret field; the
  schema has exactly four properties and none is derived from a credential. Pre-existing.
- **DuckDB sniffs a decimal CSV column as DOUBLE**, so it crosses the wire as a JSON number,
  where a Postgres NUMERIC becomes a Decimal and crosses as an exact string. For a spreadsheet of
  money that is a precision question worth revisiting.
- **An eval suite trips the new rate limit.** That is the limit working; raise
  `MAX_RUNS_PER_MINUTE` for a suite run.
- **Aborting a queued run cannot interrupt the thread it runs on**, so an in-flight model call
  finishes in the background. Its result is discarded by the guarded update.

## The database only, over tables a person chooses, built 2026-09-15

Owner's call: remove the web tool for now, answer from the database alone, and let a person
choose which tables the agent may use, twelve to start with. Six commits on `feat/table-catalog`:

| Commit | What |
|---|---|
| `405c4db` | the uncommitted router, fallback and table statistics, recorded as they stood |
| `3203026` | the web tool removed; reverting this one commit brings it back |
| `d38505a` | the guard refuses other schemas, and functions that read a table by name |
| `33204aa` | the schema readers and the relationship mapper |
| `8390d4b` | table choice, the stored catalog, its API, and the run wiring |
| `163afa2` | the tables screen |

The phase 3 and missing-data sections above describe code that no longer exists after
`3203026`. They stay as the record.

### Phase 3 is descoped

The dashboard connector, the Playwright session manager, the router, the fallback middleware,
their prompts, the `playwright` dependency and the `web_tool` SSE stage are gone from both apps,
in one commit because the stage list is part of the frozen contract. A run names its connection
again, so the Ask screen's connection picker, which the router had replaced, is back.

Migration `c94f73823b3f` soft-deletes every web connection and blanks its credential, exactly as
`delete_connection` does, so runs keep their foreign key and history still names the source. Its
downgrade is a no-op: a blanked secret cannot be restored.

### Choosing tables turned the guard's allowlist into a boundary, and it had three holes

Probed before any change, with `allowed={vehicles, alerts}`, the guard accepted
`other_schema.vehicles`, `query_to_xml('select * from secret_table', ...)` and
`table_to_xml('secret_table', ...)`. That was harmless while every `public` table was allowed,
and is not once a person has deliberately left one out.

Names are now compared the way Postgres resolves them, on a normalised copy so the SQL that runs
is still what the model wrote. A schema other than `public` (DuckDB: `main`) is refused, and so
is a function that reads a table named in a string. The connector pins `search_path=public`, so
a bare name cannot resolve anywhere else.

This limits what the agent is shown and may query. It is not a permission boundary against a
customer's own view or function that reads another table, because no check on names can see
inside one. Where that matters, narrow `analyst_ro`'s grants to the chosen tables.

### How it is split

- `app/catalog/types.py` and `relationships.py`: a table's structure and how a set of tables
  joins. Pure, and importing nothing from `app`.
- `app/connectors/pg_catalog.py`: columns from `pg_attribute` with `format_type`, because the
  Inspector renders `timestamptz` as `TIMESTAMP`; keys, unique indexes, checks and comments from
  `Inspector.get_multi_*`. A fixed handful of statements however many tables, and no row read.
  DuckDB reads an upload's columns and reports no keys.
- `app/services/tables.py`: a `connection_tables` row for every table the source exposes, a
  definition and statistics for chosen tables only, and their relationships on the connection.
- `app/agent/schema_context.py`: the query tool's description, rendered from that store.

Relationships are the declared foreign keys, plus two inferences that are always labelled
`inferred`: a column matching another chosen table's one-column key (never `id`, never a
table's own whole key, never a date, boolean or float), and `<x>_id` against a table named `x`
or its plural whose key is `id`. Only edges between chosen tables are kept, because the guard
would refuse the query that followed any other.

A first listing chooses every table when there are no more than `MAX_AGENT_TABLES`, which keeps
`demo` and small spreadsheets answering; the IoT database's 15 have to be chosen by hand. A run
on a connection with nothing chosen is a 400 before the stream opens. Runs re-read the chosen
tables once their reading is six hours old, and only ever update those rows, so two runs at once
cannot collide; tables appearing or vanishing wait for a refresh someone asks for.

Sample rows are gone, with `SCHEMA_SAMPLE_ROWS`. What the model reads about a database is now
columns, keys, a size bucket and a partition bound. The 50-row preview of a query's own result
is unchanged: it is what the model answers from.

### Evals, hard rule 6

The guard change was measured by replaying the `de39cc3c` cassettes against `main`'s code in a
worktree, without it and then with it: `golden_sql` 4/4 and 4/4, `golden_file` 7/7 and 7/7, no
drift in either.

`8390d4b` changes `QUERY_TOOL_DESC` and `SQL_CAPABILITY`, so no cassette describes the agent
after it. **There is no before/after pass rate for the catalog prompts, and rule 6 is not
satisfied for that commit.** The recording needs `demo` reseeded first, and the free tier's 20
requests a day does not cover both suites.

### Verified

- Unit tests pass and ruff is clean.
- The integration tests that leave the App DB alone pass: the tables API, the schema reader and
  read-only enforcement. They run as throwaway tenants and delete what they make.
- The full integration suite was **not** run. `clean_app_db` empties the App DB, which on this
  machine is the real account and its connections.
- `alembic upgrade head`, `downgrade -1` and `upgrade head` again, against the local `analyst`.
- Frontend: vitest, typecheck, eslint and `next build` are clean.

### Not done

| # | Item | Blocked on |
|---|---|---|
| 1 | A rule 6 pass rate for the catalog prompts | reseeding `demo`, then model quota |
| 2 | The inferred joins, checked against the real IoT schema | the SSH tunnel on 127.0.0.1:5500 |
| 3 | `sessions/` still holds Intellicar cookies, and `.env` still holds `INTELLICAR_*` | the owner's go-ahead to delete them |
| 4 | `test_schema_stats.py`, unchanged from item 4 above | reseeding `demo` |

## The database over MCP, built 2026-09-16

Owner's call: reach the customer's database through a Model Context Protocol server rather than
through an in-process connector, so that the database is a standard, reusable interface rather
than code this service maintains.

Nothing about what a person sees changed. The table picker, the stored structure, the
relationship map, the guard and the SSE contract are the ones `feat/table-catalog` shipped; only
what sits behind `SqlConnector`'s four methods moved out of this process.

### It began as a second implementation of work that was already pushed

A complete MCP rearchitecture existed uncommitted on `main` - its own server, client, contract,
metadata service, migration and table-access UI. It had been written against a `main` that was
**ten commits behind `origin/main`**, about half an hour after those ten commits were pushed.
So it re-added the web tool `3203026` had deleted, declared a `schema_cache` column
`5b7e2d9a41c3` had dropped, and carried a migration that assumed a schema that no longer
existed. It also rebuilt table choice and relationship mapping a second time, less well: only
declared foreign keys, where `app/catalog/relationships.py` already infers edges too.

`main` was fast-forwarded (it had no commits of its own) and the MCP layer rebuilt on top of the
catalog work instead of replacing it. The abandoned tree is in `stash@{0}` and under
`scratchpad/mcp-snapshot`, kept until someone confirms nothing is wanted from it.

The lesson is the cheap one: fast-forward before starting, not after finishing.

### The local App DB was inconsistent before any of this

`alembic_version` read `6df29aa84fda` while `connections` already carried `relationships` and
`catalog_refreshed_at` and had lost `schema_cache` - that is, `5b7e2d9a41c3`'s column changes had
been applied without its `connection_tables` table and without a stamp. `alembic upgrade head`
could not have run. The table was created from the model and the revision stamped; the account,
three connections and ten runs were left alone.

### How it is split

- `app/database_mcp.py` is the server, `uvicorn app.database_mcp:app --port 8001`, its own
  process because it is the only thing that decrypts a customer DSN. It exposes `SqlConnector`
  as four tools - `list_tables`, `read_tables`, `table_stats`, `run_select` - and reuses
  `pg_catalog` and `pg_stats` unchanged.
- `app/connectors/mcp.py` is the client half, an `McpConnector` that satisfies the same protocol
  the in-process one did. `connector_for` returns it for `kind="postgres"`, and **the API
  process no longer decrypts a database credential at all**.
- `app/mcp_auth.py` mints a 120-second HS256 token carrying one `tenant_id` and one
  `connection_id`, signed with `MCP_JWT_SECRET`, which is deliberately not `JWT_SECRET`: a
  stolen access token must not be replayable against the database server. Nothing in a tool's
  arguments names a connection, so a call can only reach the one its token was minted for.
- `app/mcp_client.py` is synchronous, because every caller is: the protocol is sync, the table
  routes are sync `def` in FastAPI's threadpool, and a run reaches the database through
  `asyncio.to_thread`. None of those threads has a running loop.

### The guard runs on both sides, which is not duplication here

`app/agent/tools.py` still guards before it calls, with the chosen tables it already holds for
the prompt. The server guards again, reading the selection from `connection_tables` per query.
Neither is a second source of truth - both read the same rows - and a server holding a decrypted
DSN must not be a bare SQL proxy for whoever reaches it. All three read-only layers now sit
together beside the thing that opens the connection.

### Creating a connection proves itself differently

The old smoke test was `PostgresConnector(dsn).test()` before the row existed. MCP resolves a
connection by id, so there is nothing to test that early. Listing the source is the proof now:
the row is written, `ensure_listed` reads the catalog through MCP, and a failure deletes the row
and returns the same 400 the field error already expected.

### Two processes must share `CREDENTIAL_ENCRYPTION_KEY`

That is new, and it is what the integration suite found: the server reads its own settings, so
under the suite it held a different key than the tests encrypt with and every connection failed
to open. `mcp_in_process` in `tests/integration/conftest.py` dispatches MCP calls straight at
the server's tool functions, which runs the real tools, guard and readers against the test's own
settings. The wire itself is covered by `test_database_mcp.py` and by `probe_mcp` at boot.

### Verified

- 278 unit tests and the full integration suite pass, except the three in `test_schema_stats.py`
  that were already failing on the un-reseeded `demo` fixture (open item 4, unchanged).
- `test_runs_worker.py` referenced `PreparedRun.schema`, renamed to `catalog` in `8390d4b`. It
  had never been run since. Fixed.
- The API boots with `MCP_STARTUP_PROBE=true` against a running server, and `/health` answers.
  `/openapi.json` is unchanged, so `pnpm gen:agent` needs no re-run and the frontend no change.
- End to end against `demo` through MCP: create, list, choose, read structure, stats, and
  `SELECT count(*) FROM telemetry` returning 240.
- The App DB was snapshotted before the destructive suite and restored after; the account, three
  connections and ten runs are intact.
- ruff clean. Frontend: typecheck, eslint and 159 vitest tests clean.

### Not done

| # | Item | Blocked on |
|---|---|---|
| 1 | A rule 6 pass rate for this change | it touches no prompt, so nothing is owed yet; the catalog prompts' own item stands |
| 2 | `test_schema_stats.py` | reseeding `demo`, unchanged |
| 3 | Whether anything is wanted from `stash@{0}` | the owner's read of it |
| 4 | Deploying the MCP server as a second process anywhere but a laptop | there is still no VPS |

### A source that is down, found by using it 2026-09-16

Choosing tables on the IoT connection showed a Next.js runtime error, "An unexpected response
was received from the server". The SSH tunnel on 5500 had dropped; later attempts at the same
connection succeeded, so the tunnel was flapping rather than gone.

The tunnel is infrastructure. What the tunnel exposed was two defects, both older than the MCP
change and both reachable by any unreachable source.

**Opening a connection had no timeout.** `statement_timeout` bounds a query once connected and
says nothing about connecting. A dead tunnel accepts the TCP connection locally and then never
answers, so the request hung, and the MCP server hung with it - its log stops at `Processing
request of type CallToolRequest` with no completion. Reproduced by pointing a connection at a
closed port: the PUT never returned, and was still hanging when the client gave up after 90
seconds. `connect_timeout` is now set from `connect_timeout_s` (10s), and `mcp_request_timeout_s`
(30s) bounds the API's wait on the server as a backstop.

**An unreachable source escaped as a 500.** Only `DomainError` has a handler, and
`save_selection`, `refresh` and `load_for_run` let the driver's exception through, so the browser
got a crash rather than a sentence. `create_connection` already did the right thing; these did
not. `SourceUnavailable` (503) is the error, `_reachable` in `app/services/tables.py` is where
the translation happens, and the driver's message - which quotes host, port and user - is logged
rather than returned.

Measured on the same dead port, before and after: hung past 90s, then `503` in 10.4s carrying
`could not reach that database just now - check it is running and try again`. The picker shows
that as a toast, because `normalizeAgentError` reads `error` off the body.

`TestASourceThatIsDown` in `test_tables_api.py` covers it by failing `read_tables` the way the
tunnel did: listing works, reading structure does not.

### The LangChain v1 agent architecture 2026-09-16

`create_agent` was being given four arguments - model, tools, system prompt, checkpointer - and
none of the rest of the v1 architecture. Two consequences were already live. A thread's messages
accumulated in the checkpointer with nothing pruning them, so every turn on a long thread cost
more than the last against a 200,000 token daily budget. And the agent learned nothing between
runs: it re-derived the same joins against the same schema every time, while `runs` recorded
question, SQL and answer and never read them back.

What is attached now, layer by layer. `context_schema=RunContext` carries tenant, connection, run
and thread into the graph. Tools take `ToolRuntime`, which is how `remember` files a definition
under `runtime.context.tenant_id` rather than under anything the model supplied.
`ContextEditingMiddleware` and `SummarizationMiddleware` bound a thread's context.
`PostgresStore` in the App DB, with an `InMemoryStore` behind `MEMORY_BACKEND=memory` for local
work, holds a glossary, the queries that answered earlier questions, corrections, preferences and
a per-thread record. `MemoryMiddleware` reads it once per run and writes it once.

The connector and catalog deliberately did **not** move into `RunContext`. They stay bound in the
closure `make_query_tool` builds: a tool with no way to reach another tenant's source is a
stronger guarantee than one handed the right identifier.

**`recursion_limit()` had to change, and getting it wrong would not have failed loudly.** It
counts supersteps, not model calls, and `SummarizationMiddleware` hooks `before_model`, which
adds a node to every cycle. Left alone the loop would have been cut off early while reporting
that the model gave up after too many attempts. It now takes the middleware list and counts the
four node-producing hooks the way `create_agent` counts them. `wrap_model_call` and
`wrap_tool_call` produce no node, which is why memory is read through a wrap hook and costs
nothing.

**`2 * max_tool_calls + 1` was itself off by one, and had been since it was written.** Writing a
test that spends the whole budget rather than asserting the arithmetic found it. LangGraph raises
when the superstep count *reaches* `recursion_limit`, so a run needing N supersteps needs a limit
of N + 1. Measured on `main`, with `MAX_TOOL_CALLS=6`: four tool calls completed, five completed,
six raised `GraphRecursionError`. Every customer who asked a question needing the sixth query was
told the agent gave up after too many query attempts, which is not what happened. The minimum
working limit was measured for each configuration rather than reasoned about - 14 bare, 21 with
context management, 23 with memory as well - and the formula now returns exactly those.

Both of the arithmetic's failure modes are now driven end to end rather than asserted:
`TestTheWholeToolBudgetIsSpendable` spends every permitted tool call and answers, and its second
test pins that the old bound would have cut the same run short.

**The SSE contract is untouched and stays untouched by accident of an exact match.**
`EventTranslator` dispatches on `node == "model"` / `node == "tools"`. Middleware nodes are named
`<middleware>.<hook>`, so they are ignored. That matters more than it looks: summarisation's
update carries the whole preserved message tail, and a prefix match would have replayed a
thread's history to the customer as `token` events.

`TestSummarisationActuallyFiring` makes the summariser really run, with its own model, rather
than feeding the translator a node name by hand. Its update was observed carrying
`RemoveMessage, HumanMessage, AIMessage, ToolMessage` - an AIMessage and a ToolMessage
indistinguishable from the ones the `model` and `tools` nodes emit - while the stage sequence
stayed the frozen five and exactly one `token` event reached the client.

**Two defects found while building, both of which would have shipped.**

`PostgresStore.from_conn_string(str(app_db_url))` fails. `APP_DB_URL` is a SQLAlchemy URL and
carries a `+psycopg` driver suffix; psycopg parses the DSN itself and rejects it. `CHECKPOINT_DB_URL`
has no suffix precisely because LangGraph opens that one directly. `store.py` strips the suffix,
and two unit tests pin it.

Alembic would have dropped the memory. Verified rather than assumed: with `include_object`
removed, `--autogenerate` emits `op.drop_table('store')` and `op.drop_table('store_migrations')`.
With it in place the same command produces an empty migration.

That verification was a pair of throwaway revisions run by hand, which protects nobody once they
are deleted, and `alembic/env.py` cannot be imported by a test because it runs migrations at
import. So `LANGGRAPH_TABLES` and the predicate moved into `app/agent/store.py` - the module that
creates the tables is the one that names them - and `env.py` imports it.
`test_alembic_excludes_the_store.py` now runs `compare_metadata` for real, asserts the diff is
empty, and runs the same comparison with the filter removed to prove the guard is load-bearing
rather than vacuously true.

**Numbers chosen.** Clearing trips at 12,000 tokens and summarising at 24,000, so the free
mechanism runs first and the one that costs a model call is the fallback. `WORKER_MAX_JOBS` drops
from 4 to 3: a job now holds an App DB session, a checkpoint connection, a store connection and a
customer DB connection against a pool of 5 plus 10 overflow. `SummarizationMiddleware` is given
an explicit `trigger`; its default is `None`, which makes it a silent no-op rather than a default,
and a test asserts the trigger is armed.

**Owed: rule 6.** The prompts file gained a summary prompt and a memory template, and the model is
offered a second tool, so the golden suite has to be re-recorded and the before/after pass rate
reported. It could not be run here. Note the cassettes were **already** stale before this change:
`prompt_sha()` at HEAD is `12f02ab9` and the cassettes on disk are `de39cc3c`, so `--replay` was
already failing on `main`. Re-recording needs `TOKEN`, `CONN` and a day of free-tier quota.

Not done: the end-to-end checks that need a live model - that summarisation fires on a real long
thread against Gemini rather than a scripted one, and that a definition taught in one thread is
applied in a new one against the real model. Both are covered by unit tests with fakes; what is
missing is the live confirmation.

### A turn was keeping the thread's SQL, not its own 2026-09-16

Found by reading the store after five questions were put through the running agent, not by a
test. Thread `6d1a3148` asked "How much vehicles are present in database ?", then "How much ?",
then "Can you tell me the question ?". The third run recorded no SQL in `runs` and yet a
`queries` memory was written for it, pairing that question with
`SELECT COUNT(*) FROM vehicles LIMIT 500` - the query two turns earlier.

`_harvest` took `state["messages"]`, which under a checkpointer is the whole thread rather than
the run that just finished. So `sql` was the last successful tool artifact *anywhere* in the
thread, and `answer` the last content-bearing AIMessage anywhere in it. A turn that ran no query
inherited both. The pair is not merely useless: `recall` offers remembered queries back as
precedent, so a conversational aside teaches the model that a question about what was just asked
is answered by counting vehicles.

`_this_turn` now slices the thread at its own question - the last human turn that is not a
summary the summariser wrote back in - and everything is harvested from that slice.

Why no existing test saw it: `run()` in `test_middleware.py` builds a fresh graph per call with
no checkpointer, so nothing it drives ever carries a previous turn into `after_agent`.
`test_a_question_answered_without_sql_keeps_no_query` passed because there was no earlier SQL to
inherit. `run_thread` drives several turns down one `InMemorySaver` thread instead, which is the
shape that breaks. Checked load-bearing rather than assumed: with `_this_turn` reverted, two of
the three new tests fail with `assert 'SELECT vehicleno FROM vehicles LIMIT 500' is None`, the
same symptom as the live store.

364 unit tests pass, lint clean. The polluted row is still in the local store; it is one
`queries` entry under the live tenant and nothing has recalled it yet.

## Phase 5b — multi-file datasets, built 2026-09-17

A dealer customer's data is several sheets and CSVs, usually with a title above the header and a
Grand Total at the bottom. A `kind="file"` connection is now a dataset: many uploaded files
contributing tables to one DuckDB. The agent, the guard, the SSE contract, `database_mcp.py` and
`connectors/mcp.py` are untouched, and `DuckDBConnector` is the same class.

### What shipped

- `POST /connections/file` takes 1 to 20 files as `files`, plus `name`. `POST
  /connections/{id}/files` adds files and `DELETE /connections/{id}/files/{filename}` removes one;
  both return `TablesOut`. Every change to a dataset ends with `tables.refresh`, so added tables
  arrive unselected and a removed file's tables drop, selected or not.
- The secret is `{"sources": [{"table", "path", "file", "origin", "profile"}]}`. `origin` is
  always `"upload"` for now. The old secret shape is not migrated; the local App DB held no live
  file connection when this shipped.
- Each ingest writes into a fresh `file_store_dir/{tenant}/{connection}/{uuid}/`. A batch is
  all-or-nothing: any failure removes that directory (the whole connection directory on a
  create) and returns a 400 naming the file. A filename already in the dataset, or twice in one
  request, is refused before anything is written, because removal is by filename.
- Limits: 25 MB per file (`max_upload_bytes`), 1 to 20 files per request (422 from
  `File(min_length, max_length)`), and `max_dataset_bytes`, 100 MB of Parquet across the dataset.
- Naming: a CSV, TSV or Parquet file, or a workbook with one non-empty sheet, is named after the
  file; a workbook with several is `stem__sheet`; a name already taken gets `_2`, `_3`.
- `ConnectionOut.file_count` and `TableOut.file` are new. Both come from the secret, decrypted
  once per connection, through `registry.file_sources`, so `registry.py` is still the only place
  a file secret is decrypted. A Postgres connection is refused by both file routes before its
  secret is read.
- Adding and removing take `SELECT ... FOR UPDATE` on the connection row, so two requests at once
  cannot write over each other's secret and orphan a batch.

### Ingest hardening, and where the spec's literal rules were wrong

Every frame, whatever the format, goes through one vectorised pass: header row found under any
title lines, entirely-null `Unnamed:` columns dropped, trailing `Total` / `Grand Total` rows
dropped and counted, day-first date text parsed, and every name slugged. The profile keeps
`row_count`, `header_row`, `dropped_total_rows`, the original column names and each date column's
range.

Four rules were measured against pandas 3.0.5 and duckdb 1.5.5 before they were written, and
three of them had to change.

1. **`pd.to_datetime(dayfirst=True, errors="coerce")` corrupts dates.** It reads `2026-07-01` as
   7 January, because with `dayfirst` the inferred format for an ISO string is `%Y-%d-%m`. It
   turns `July` and `Jul-26` into year-1 timestamps and integers into 1970. A column whose first
   value is not a date falls back to per-element dateutil with a warning. Decided at planning: a
   format-guarded parse instead. The format is guessed from the first non-numeric value with
   `guess_datetime_format`, day-first unless the value starts with a four-digit year. It is used
   only if it carries a day and a year, then applied with `format=`, under the same 90% rule.
2. **"A different mix of types" had to mean the set of kinds**, meaning text, number (including
   numeric strings) and other, among the non-empty cells. Compared cell by cell, a two-line title
   is detected at row 1 rather than 2. A `header=None` CSV probe is all strings, which is why
   numeric strings count as numbers.
3. **Slugging did not make a valid identifier.** All 75 reserved keywords and 30 others (`order`,
   `group`, `left`, `join`) fail unquoted; a file named `order.csv` broke `CREATE TABLE`. A name
   in any `duckdb_keywords()` category other than `unreserved` gets a trailing `_`. The `_2`
   suffix on a 63-character name also overflowed the identifier limit; the stem is shortened now.

The fourth held. The delimiter still comes from DuckDB's `sniff_csv`: pandas with a fixed `sep`
would read a `;` file as one column, silently.

### The model sees a size, not the profile

Decided at planning: `table_stats` returns `rows`, plus `rows_approx` above 1,000 rows, through the same
`row_bucket` and `row_magnitude` Postgres uses (renamed from `_bucket` / `_magnitude`). The date
ranges stay in the encrypted secret. `schema_context.py` renders `covered_to` as "a partition
ending", which is false for a file, and the 2026-09-12 decision was bounds only, never a value
read out of a row.

### Verified

- 568 tests: 390 unit, 178 integration. Lint and format clean; mypy adds nothing to its existing
  errors.
- Unit: 390 pass. Integration was run against the real local App DB after snapshotting the seven
  tables it touches (`refresh_tokens`, `users`, `runs`, `connection_tables`, `connections`,
  `tenants`, `store`) and restored afterwards, with row counts and content hashes matching the
  snapshot.
- Full suite: 561 passed, 2 skipped (model key), 4 failed, with coverage at 95% overall and 100%
  on `sql_guard.py` and `app/security/`. Three of the failures are `test_schema_stats.py` on the
  un-reseeded `demo`, unchanged. The fourth was not recorded here before and is not caused by
  this work; see below.
  `test_file_connection.py` passes 23 of 23, including one test added after the full run for the
  empty-batch-directory branch.
- Three of the new integration tests were checked load-bearing: removing the batch cleanup, the
  Parquet unlink or the dataset cap each fails its test, and restoring it passes.

### Found, not caused: `TestParity` fails on `main`

`tests/integration/test_runs_worker.py::TestParity::test_the_queued_stream_is_identical_to_the_in_process_one`
fails with `the run stopped responding`. It fails identically on `a0abc63` with this work stashed.
The test sets `run_stall_timeout_s` to 0.5s, and the reader gave up after 0.5s on a run that
finished in 1.9s. Nothing here touches the queue or a Postgres run; it is left for its own fix.

### Limits and open items

| # | Item |
|---|---|
| 1 | A CSV whose title lines are not padded with delimiters fails to parse and returns a 400 naming the file. Excel pads them when it saves as CSV. |
| 2 | `DuckDBConnector` loads the whole dataset into memory under a 512 MB limit on every picker action and run; 100 MB of Parquet can expand past that. |
| 3 | The `golden_file` cassettes will not replay: file tables now render a row-size line in the tool description. No prompt or guard changed, so rule 6 owes no A/B for this. |
| 4 | `analyst-agent-frontend/lib/api/types.ts` does not carry `file_count` or `file`, and the frontend has no upload UI yet. |
| 5 | C: fills up on this machine, and `TMPDIR` points at it and overrides `TEMP`. Run the suite with `TMPDIR` and `--basetemp` on D:. |
| 6 | Not yet done against a running API: a three-file join through a live model, adding a fourth file, removing one, and a real dealer sheet with a title and a Grand Total. |

## Identity moves to Supabase, built 2026-09-17

Owner's call: Supabase Auth handles authentication, with "Continue with Google" live. This reverses
deviation 13. Supabase is used for identity only; tenants and everything else stay in the App DB.

### What shipped

- **Backend.** `app/security/supabase.py` verifies the project's ES256 access tokens against its
  JWKS (algorithm pinned, `aud=authenticated`, issuer checked, `role=authenticated`, anonymous
  users refused), with no shared secret. `current_tenant` resolves the tenant from
  `users.auth_user_id`, so a deactivation takes effect on the next request. A signed-in person
  with no account gets 403 `{"code": "onboarding_required"}`; `POST /auth/provision` creates
  their organisation. An account from before Supabase is adopted by the first sign-in whose
  token proves the same email (`user_metadata.email_verified`); an unverified address adopts
  nothing. Migration `0f6da5ee636c` adds `auth_user_id` and drops `password_hash` and
  `refresh_tokens`. `/auth/register|login|refresh|logout`, Argon2 and `JWT_SECRET` are gone.
- **Frontend.** Supabase is called only from server actions, route handlers and `proxy.ts`, with
  httpOnly session cookies; no Supabase code or key ships to the browser (checked in
  `.next/static`). Google goes out through a server action and back through
  `/api/auth/callback`; a first-time user names their organisation on `/welcome`. Email sign-up
  names it on the form and `/api/auth/confirm` creates it when the link is opened.
- **Scripts.** `scripts/supabase_token.py <email>` prints a token for the evals and check scripts.

### Verified

- Backend: 381 unit tests. Integration suite: 153 passed, 2 skipped, 4 failed; one was a stale
  `u_test` assertion in `test_runs_api.py`, fixed and passing on rerun, and three are
  `test_schema_stats.py` (below). `alembic check` clean; downgrade and upgrade round-trip.
- The App DB was snapshotted before the suite and migration and restored after: 3 tenants,
  2 users (unlinked until they sign in), 3 connections, 16 connection tables, 27 runs.
- Against the live project: a token naming the project's real key id but signed elsewhere is
  refused with "Signature verification failed", so the JWKS is fetched and used.
- Frontend: typecheck, lint, 249 tests, production build. Signed-out navigation redirects to
  `/login?next=`, and the callback and confirm handlers send a failure to `/login?error=`.

### Not done

- **A real email sign-up and confirmation, end to end.** Custom SMTP (Gmail) was configured on
  2026-09-17; whether the "Confirm signup" template links to
  `{{ .SiteURL }}/api/auth/confirm?token_hash={{ .TokenHash }}&type=email` is not yet confirmed
  by use. That run is also where `user_metadata.email_verified` must be seen on an email token:
  if it is absent there, older accounts can only be adopted through Google.
- The two accounts from before Supabase (`test@gmail.com`, `filetest@gmail.com`) are unlinked
  and hold the existing connections; they are adopted only by a verified sign-in with that
  address.

### Verified by the owner, 2026-09-17

Google sign-in works end to end against the live project. A new Google user reached `/welcome`
(the agent logged `/auth/me` 403, then `/auth/provision` 201, then `/auth/me` 200), and the App
DB holds an owner linked by `auth_user_id` to the Supabase user. Supabase recorded the identity
as `google` with `email_verified: true` in both `raw_user_meta_data` and the identity data, so
the claim adoption relies on is present on Google tokens.

### Found, not caused: `test_schema_stats.py` needs the demo database reseeded

Three tests fail with `KeyError: 'trips'` and `'gps_pings'`. They read the demo database
directly, never the API, and their docstring says to reseed `scripts/demo_customer.sql` first.

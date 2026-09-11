# STATUS

Source of truth for the active phase. Phase N+1 does not begin until phase N's line reads
**done**. Update this file as the last step of every task.

| Phase | Deliverable | Done when | State | Date |
|---|---|---|---|---|
| 0 | repos, Compose, stub graph, SSE endpoint | `curl -N /runs` streams a stub, trace in LangSmith | **done**, tracing dormant | 2026-09-10 |
| 1 | SQL tool on our own IoT DB, guard, evals | `evals/run_evals.py` >= 25/30 | code complete, **gate paused** | 2026-09-10 |
| 2 | JWT auth, vault, `/connections`, then frontend Part B | second person connects a DB without help | **in progress** | backend auth, history and delete shipped 2026-09-11; frontend building |
| 3 | web tool (Playwright) | Intellicar live query works for two tenants with separate sessions | **done**, verified live | 2026-09-11 |
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
13. **Sign-up and sign-in live in the agent, not the web app.** The ownership table assigned
    identity to Supabase inside analyst-web. Owner's call on 2026-09-11: put identity beside
    the data it protects. The cost is a `users` table, Argon2id and `/auth/*` here; the payoff
    is that the browser never holds a token, the web app never holds the signing secret, and
    `decode_token`, `TenantContext` and every existing route were untouched, because the new
    endpoints mint exactly the claim shape this service already accepted. Hand-minted tokens
    therefore still work everywhere, which is what keeps the eval harness running.
14. **Refresh tokens are opaque, not JWTs.** `decode_token` accepts any correctly signed token
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

## Known limits and open checks

| # | Item | Blocked on |
|---|---|---|
| 1 | `LANGSMITH_API_KEY` | the tracing half of phase 0's done-line |
| 2 | The 30 IoT golden cases | the telemetry backfill, unchanged |
| 3 | The hard rule 6 A/B on the IoT prompt | item 2; the harness makes it two commands |

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

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read first

`DEVELOPMENT.md` is the authoritative spec for this workspace — read it fully before writing code. `analyst_saas_implementation_manual.pdf` (repo root, 44 pages, 16 sections) is the step-by-step manual with every file, command and checkpoint; section numbers in `DEVELOPMENT.md` refer to it.

The PDF cannot be opened by the Read tool here (`pdftoppm` is not installed). To read it:

```bash
python -m pip install pypdf
python -c "import pypdf;r=pypdf.PdfReader('analyst_saas_implementation_manual.pdf');open('manual.txt','w',encoding='utf-8').write(''.join(p.extract_text() or '' for p in r.pages))"
```

Extraction is lossy — it inserts a space after capitals (`Any` becomes `A ny`, `START` becomes `STA RT`) and tabs between tokens. Read it for structure and intent; never copy code out of it verbatim.

## Current state of the workspace

`analyst-agent/` is built through phase 5: two connector kinds (Postgres and an uploaded file; the web dashboard was removed on 2026-09-15), a per-connection choice of the tables the agent may read with their structure stored beside it, the guard, the SSE contract, an arq worker behind a flag, per-tenant limits and usage, an offline eval harness, and the LangChain v1 agent architecture: runtime context, tool runtime, context management, the store, checkpoints and middleware. `analyst-web/` does not exist yet, which is what phase 2 is still waiting on.

`docs/STATUS.md` is the source of truth for the active phase. Phase N+1 must not begin until phase N's "done" line is true; phases 3 to 5 were built with 1 and 2 still open, on Apoorv's decision, and that deviation is recorded there.

## What we are building

A multi-tenant SaaS that answers business questions over a customer's own data. The customer connects a source (Postgres or an uploaded file), chooses which of its tables the agent may read, and asks in plain English. The service writes a read-only SQL query against those tables, validates and executes it against *that tenant's source only*, and streams back the answer, the SQL, and a result table.

Reference behaviour is the existing TypeScript `iTarangIT/Data-Analysis-Agent` repo; this is a rebuild as a product. Owner: iTarang (Apoorv).

```
Customer browser
      |
      v
Next.js (analyst-web) -- App Postgres (users, tenants, usage)
      |  HTTP + SSE   (OpenAPI contract, Bearer JWT carrying tenant_id)
      v
analyst-agent (Python 3.12, FastAPI, LangGraph)
      create_agent:  model <--> tools   (loop until the model stops calling tools)
                       query_database  -> sql_guard -> connector
                         described from, and allowed only, the connection's chosen tables
      Postgres checkpointer | LangSmith
      |                                         |
      |  MCP (streamable HTTP, 120s token       |  in process
      |       naming one tenant + connection)   v
      v                                    DuckDB -> Uploaded files
database MCP server (app/database_mcp.py, its own process on :8001)
      list_tables · read_tables · table_stats · run_select
      credential vault (Fernet) -> the only place a DSN is decrypted
      sql_guard again | analyst_ro role | read-only connect_args
      |
      v
Customer DB (read-only)
```

The browser never holds a token at all. It talks only to Next.js route handlers, which hold the access token in an httpOnly cookie and attach it server-side. Identity moved into this service: it owns the `users` table, hashes passwords with Argon2id, and mints the 15-minute access token itself.

### Who owns what

| Concern | analyst-web (Next.js) | analyst-agent (Python) |
|---|---|---|
| Sign-up / login | forms, cookies, proxying | **owns it**: `users`, Argon2id, `/auth/*` |
| Tenant + membership | — | a signup creates a tenant; `tenant_id` still only ever comes from the JWT |
| Agent JWT | never sees the signing secret | mints and verifies HS256 `{tenant_id, sub}`, 15-min expiry |
| Sessions | stores both tokens in httpOnly cookies | rotates a revocable refresh token, with a reuse-detection family |
| Connections | form UI, calls `POST /connections` | validates, encrypts, stores |
| Chat | SSE client, renders events | streams events |
| Billing | Razorpay/Stripe checkout + webhooks, sets `plan` | reads `daily_token_budget` |
| Usage display | reads `runs` aggregates via a Next.js API route | writes `runs` |

**Backend ships first; the web client is generated from the running agent's `/openapi.json`.** Never hand-write the agent client.

## Commands

Local development runs on **native Windows Postgres 16 — no Docker** (`DEVELOPMENT.md` §3 has the full setup and the one-time `psql` bootstrap). One server on `localhost:5432` holds three databases: `analyst` (App DB, Alembic), `checkpoints` (LangGraph), `demo` (seeded customer DB, read through the `analyst_ro` role). The manual's 5433/5434/5435 are Compose ports — ignore them locally. `docker-compose.dev.yml` stays in the repo for CI and the VPS; never assume it is running.

analyst-agent (PowerShell):
```powershell
.\.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
uvicorn app.database_mcp:app --port 8001         # the database MCP server; the API will not boot without it
alembic revision --autogenerate -m "msg"; alembic upgrade head
pytest -m "not integration"                      # fast, no DB
pytest -m integration                            # needs the three local databases
pytest tests/unit/test_sql_guard.py::test_name   # single test
ruff check app tests; ruff format app tests
$env:TOKEN="..."; $env:CONN="..."; python evals/run_evals.py   # live gate, >= 80% or not done
python evals/recorded.py --record --only 0-9    # capture the model; the free tier is 20/day
python evals/recorded.py --replay               # rerun the suite offline, no API calls
$env:MAX_RUNS_PER_MINUTE="100"                  # a suite trips the per-tenant rate limit
pip-compile --extra dev -o requirements.lock pyproject.toml    # after any dependency change
```


### The queue (phase 4)

`QUEUE_ENABLED` defaults to false, which runs the agent in this process and needs no Redis.
With it on, `POST /runs` enqueues and reads the run's frames back from `run:<id>`:

```powershell
$env:QUEUE_ENABLED="true"; arq app.workers.runs.WorkerSettings
arq app.workers.runs.WorkerSettings --watch app     # reload on edit
```

Redis is **Memurai**, a native Windows service on 6379. Its CLI is `memurai-cli`, not
`redis-cli`. Ctrl-C does **not** stop an in-flight arq job on Windows: `add_signal_handler` is
unsupported there, so arq registers no handler and its shutdown waits for the running task. Use
`Stop-Process -Force` to test what a lost worker looks like.

analyst-web:
```bash
pnpm dev
pnpm gen:agent        # regenerates src/lib/agent/openapi.d.ts against a RUNNING agent
pnpm lint && pnpm vitest run --coverage
pnpm vitest run src/hooks/useRun.test.tsx        # single test file
pnpm playwright test  # needs agent + local Postgres + pnpm dev running
```

## Architecture invariants

**analyst-agent** — `app/api/` (HTTP only) · `app/services/` (business rules, domain errors) · `app/agent/` (`graph.py` builds the `create_agent` harness, `prompts.py`, `tools.py`, `nodes/sql_guard.py`, `context.py` what a run is, `middleware.py` what wraps the loop, `memory.py` what it remembers, `store.py` where that lives) · `app/connectors/` (customer sources: `base.py` protocols, `mcp.py` which reaches Postgres through the MCP server, `pg_catalog.py` and `pg_stats.py` which read the catalog, `duckdb.py`, `registry.py`) · `app/database_mcp.py` (the MCP server itself, its own process), `app/mcp_client.py`, `app/mcp_auth.py` · `app/catalog/` (`types.py` a table's structure, `relationships.py` how tables join; imports nothing from `app`) · `app/security/` (`auth.py` JWT, `vault.py` Fernet) · `app/db/` (App DB session + models: Tenant, Connection, ConnectionTable, Run; `Run` is the usage ledger, there is no separate `Usage` table) · `app/workers/` (`runs.py` the arq worker) · `app/queue.py` · plus `evals/`, `scripts/`, `tests/{unit,integration}`. Nothing imports upward. `HTTPException` is raised only inside `app/api/`; everything else raises from `app/services/errors.py`.

- The agent is built with `langchain.agents.create_agent`, whose graph is a `model` node and a `tools` node looping until the model stops calling tools. There is no hand-written router: the model decides whether a question needs a tool. The loop is bounded by `recursion_limit()`, derived from `max_tool_calls` and the middleware attached.
- Middleware is where anything wrapping the loop goes. Only `before_agent`, `before_model`, `after_model` and `after_agent` become graph nodes; `wrap_model_call` and `wrap_tool_call` compose around the model and tool nodes and cost nothing. `recursion_limit()` counts supersteps, so it takes the middleware list and must grow with it — left at the bare `2 * max_tool_calls + 1` a summarising agent gives up after four queries and reports that the model did.
- A thread's context is bounded by two things, cheapest first: `ContextEditingMiddleware` replaces old tool results with a placeholder in a copy of the messages, so nothing reaches the checkpoint and no model call is spent; `SummarizationMiddleware` then summarises what is left, which does cost a call. Its `trigger` is never left at the default — `None` means it can never fire, silently.
- Long-term memory is read once per run in `before_agent` and written once in `after_agent`; the read is injected through `wrap_model_call`, so recalling costs no extra node and no extra model turn. Namespaces are tenant-first, and a glossary, a remembered query and a correction are per connection as well — a definition means nothing against a different customer's schema. A thread record keeps the question, the SQL and the answer, and never result rows.
- Capabilities are LangChain tools defined with the `@tool` decorator in `app/agent/tools.py`, one per tenant connection. Each returns `content_and_artifact`, so the model sees a row preview while the caller keeps the full result for the `rows` event.
- `app/agent/nodes/sql_guard.py` is the most important file in the service and is **pure sqlglot code that must never call a model**. It is called from inside every tool, because a tool is invoked by the model and cannot assume anything guarded first: SELECT only, one statement, tables in `public` (DuckDB: `main`) only, table allowlist from the tables chosen for the connection, LIMIT injected, every mutating expression type rejected (`Insert`, `Update`, `Delete`, `Drop`, `Alter`, `Create`, `Command`, `Merge`, `TruncateTable`, `Grant`), and functions that read a table named in a string (`query_to_xml`, `table_to_xml`, `dblink`, …) rejected. Choosing tables limits what the agent is shown and may query; the database role's GRANTs remain the hard boundary, because a customer view or function that reads other tables cannot be caught by name.
- A connection's tables live in `connection_tables` (`app/services/tables.py`): every table the source exposes, which ones are chosen (at most `MAX_AGENT_TABLES`), and for the chosen ones only their definition and statistics. Relationships between chosen tables sit on the connection. `app/agent/schema_context.py` renders that into the query tool's description. Columns, keys and a size bucket are stored and shown to the model; a row never is.
- `app/security/vault.py` is the only module that sees plaintext credentials. `decrypt()` is called from `app/connectors/registry.py` for a file source, and from `app/database_mcp.py` for a database. **The API process never decrypts a Postgres DSN** — only the MCP server does, which is why it is a separate process. No API response may contain `secret_enc`, `dsn`, or `password`.
- Every function under `connectors/` and `agent/` takes an explicit `tenant_id` — never optional, never defaulted, never inferred from anything but the JWT. Checkpointer thread ids are `f"{tenant_id}:{thread_id}"`. Inside the agent that identity travels as `RunContext`, reached through `ToolRuntime`: a tool namespaces what it writes by `runtime.context.tenant_id` and never by an argument the model supplied, the same refusal `database_mcp.py` makes when it reads tenant and connection only from a verified token.
- Three distinct databases, never conflated: **App DB** (ours, Alembic-migrated), **Checkpoint DB** (LangGraph-managed, disposable), **Customer DB** (theirs — read-only role, never migrated, never written). The App DB additionally holds LangGraph's `store` and `store_migrations`, which are the agent's long-term memory: they live here rather than in the checkpoint database because that one is disposable and memory is not. LangGraph creates them, so `alembic/env.py` excludes them by name — without that, the next `--autogenerate` writes a migration dropping both.
- Customer DB read-only is enforced at three independent layers, all of which now live in the MCP server beside the thing that opens the connection: the Postgres role (`default_transaction_read_only=on`), the engine's `connect_args`, and the guard. `app/agent/tools.py` guards as well, before it calls — the MCP server does not trust its caller, and the caller does not assume the server guards. Verify with a DELETE that must fail.
- A database is reached **only** through MCP. `connector_for` returns an `McpConnector` for `kind="postgres"`, and every call carries a 120-second token naming one tenant and one connection; nothing in a tool's arguments names a database, so a call can only reach the one its token was minted for.

**analyst-agent-frontend** — Next.js 16, App Router, no `src/`. `app/(auth)/{login,register}` · `app/(app)/{ask,connections,connections/[connectionId]/tables,runs}` · `app/api/` (the only place the access token is attached) · `components/{ui,app-shell,auth,connections,ask}` · `features/ask/` (the SSE state machine) · `features/connections/` (the table picker's rules) · `lib/{api,auth,sse}` · `proxy.ts`, which is what Next 16 calls middleware and which only ever reads the cookie.

- Route handlers under `src/app/api/` are the only files holding `SUPABASE_SERVICE_ROLE_KEY` and `AGENT_JWT_SECRET`.
- `src/lib/agent/` (`openapi.d.ts` generated · `client.ts` openapi-fetch · `token.ts` jose, server-only · `sse.ts`) is the single boundary to the Python service. If the contract changes, only this folder and the generated types change.
- `hooks/useRun.ts` is a state machine — `idle → routing → sql → rows → answering → done | error` — driven purely by SSE events, so the UI renders agent state rather than holding a second copy of the logic.
- SSE uses a native `fetch` + `ReadableStream` parser, not `EventSource`: `/runs` is a POST with a body.

## SSE contract (frozen)

Changing it requires updating both repos in the same PR.

| event | data |
|---|---|
| `status` | `{"stage": router\|sql_gen\|sql_guard\|db_exec\|answer}` |
| `sql` | `{"sql": "..."}` |
| `rows` | `{"columns": [...], "rows": [[...]], "truncated": bool}` |
| `chart` | `{"type": bar\|line, "x": "col", "y": ["col"]}` — optional, always straight after a `rows` |
| `token` | `{"text": "..."}` |
| `done` | `{"run_id": "...", "duration_ms": n}` |
| `error` | `{"message": "..."}` |

`chart` was added in phase 5, before `analyst-web` existed, so there was no second repo to
update in the same PR. It is additive: no existing event changed shape, it always follows a
`rows` event for the same tool call, and it adds **no new stage** — the stage list is unchanged,
because a chart is a payload rather than a step. A client that ignores unknown event names is
unaffected. Note that `pnpm gen:agent` will not surface it: SSE events do not appear in
`/openapi.json`.

## Hard rules

These override normal judgement and default behaviour.

### Code style

1. **No unnecessary comments.** Comment only what the code cannot say itself: a non-obvious *why*, a workaround and the reason it exists, an invariant that isn't visible locally. Never restate what a line does, never add section-divider banners, never narrate steps, never leave `TODO` or placeholder comments in delivered code. A docstring belongs on a public function whose contract isn't obvious from its signature — not on every function.
2. **Code must read as human-written.** No tells: no defensive `try/except` around code that cannot fail, no re-validating what a Pydantic model or zod schema already guaranteed, no handling of edge cases nobody asked for, no ceremonial abstraction (a wrapper with one caller, a config object for two arguments), no over-explaining names like `sql_string_value`.
3. **Follow how humans actually write code in this stack.** Match the idioms of the surrounding file and of the framework itself — FastAPI dependencies, SQLAlchemy sessions, LangGraph node signatures, Next.js route handlers and Server Components. Reach for the plain, direct construction a working engineer would write, not the clever or maximally general one. When a file already exists, its conventions beat your defaults.
4. **Write optimized code.** Correct data structure, one pass over the data, one query where one query suffices. No N+1 queries, no fetching inside a loop, no recomputing per row what can be computed once, no loading a full result set just to count it. Push work into SQL when SQL is where it belongs. Optimize the query and the algorithm — never trade clarity for micro-optimisation or for fewer characters.

### Product rules

5. Every LLM call has a Pydantic output schema or a single-string contract. Never regex-parse model output.
6. Prompts live only in `app/agent/prompts.py`. Changing a prompt or the guard means running evals and reporting the before/after pass rate in the PR. Every phase adds cases to `evals/golden_sql.yaml`; a PR that lowers the pass rate is not merged.
7. Do not require Docker for local development. Anything that only works inside a container belongs in CI or on the VPS.
8. Do not add Redis/queue before phase 4 — until then any Redis path sits behind a feature flag defaulting to off. Do not add a second DB connector until a paying customer asks.
9. Keep the graph in Python. If heavy analytics is needed, add a tool, not a second orchestrator.
10. Do not build "a quick UI to test the backend" — `curl -N` and `evals/run_evals.py` are the UI until phase 2 is done.
11. Never commit `.env`, `sessions/`, a `requirements.lock` without its matching `pyproject.toml` change, or a generated `openapi.d.ts` that doesn't match a running agent.
12. If a request would weaken any rule here, stop and ask Apoorv rather than complying.

## Conventions

- Python: ruff, line length 100, type hints everywhere, `structlog` with `tenant_id`/`run_id` bound in contextvars.
- TypeScript: strict, zod at every boundary (env, forms, route bodies), no `any`, server-only secrets never imported into client components.
- Tests: unit tests mock the LLM; integration tests are marked `integration` and need the three local databases. Coverage floors — 85% on `sql_guard.py` and `security/`, 70% overall; 90% on `src/lib/agent/`, 80% on `src/hooks/`.
- Commits: `feat(agent): ...`, `fix(web): ...`, `chore: ...`. One phase item per PR.

## Done means

Tests pass, lint clean, `pnpm gen:agent` re-run if the agent API changed, evals run and pass rate reported if prompts or the guard changed, the manual's checkpoint for that section executed and its expected output observed, and `docs/STATUS.md` updated.

## Manual section map

§2 environment · §3 project structure · §4 FastAPI settings/logging/LLM client/app factory · §5 the three databases (5.5 read-only role + demo data, 5.6 connector and schema introspection) · §6 API (6.1 auth, 6.2 vault, 6.4 connections, 6.5 runs SSE) · §7 the agent (7.5 guard, 7.7 Playwright web tool, 7.9 run service + usage, 7.11 golden evals) · §8 testing · §9 deployment (9.3 Compose, 9.5 CI, 9.6 readiness) · §10–15 the Next.js shell (12 structure, 13 auth/tenant/JWT, 14.3 SSE parser, 14.4 `useRun`) · §16 appendix (16.2 extension points, 16.3 troubleshooting index).

Phase 5 extension points are already designed (§16.2): the file tool is a `DuckDBConnector` plus `kind="file"` on `Connection` with the guard dialect switched to `duckdb` — nothing else in the graph changes; charts are a second structured output from `answer_node` streamed as a `chart` event; the queue moves `stream_run`'s try-block into an `arq` task.

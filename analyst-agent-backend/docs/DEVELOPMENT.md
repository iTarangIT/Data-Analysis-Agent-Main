# DEVELOPMENT.md — Data Analyst SaaS

Instructions for Claude Code working in this workspace. Read fully before touching code.
Full manual with every command, file and checkpoint: `docs/analyst_saas_implementation_manual.pdf` (also `docs/manual.md`). Section numbers below refer to it.

## 1. What we are building

A multi-tenant SaaS where a customer connects their own data source (a Postgres database or an uploaded file), chooses which of its tables the agent may read, asks a question in plain English, and gets an answer with numbers, the SQL used and a result table. Owner: iTarang (Apoorv). Reference behaviour: the existing `iTarangIT/Data-Analysis-Agent` repo (TypeScript). We are rebuilding it as a product.

Two repos, one workspace:

| Repo | Stack | Role |
|---|---|---|
| `analyst-agent/` | Python 3.12, FastAPI, LangGraph, SQLAlchemy, Alembic, sqlglot | the agent — routing, SQL generation, guard, execution, streaming |
| `analyst-web/` | Next.js 16 App Router, TypeScript strict, SWR, shadcn, Tailwind v4 | product shell — auth screens, connections UI, ask workspace, history |

They talk over one contract: `POST /runs` (SSE), `/connections` and `/runs` history on the agent, authenticated with a **Supabase Auth** access token (ES256). The web app signs people in with Supabase from the server, holds the session in httpOnly cookies and attaches the token server-side; the agent verifies it against the project's JWKS and resolves the tenant from the linked account. **Backend is built first; frontend is generated from the backend's `/openapi.json`.**

## 2. Current phase

Check `docs/STATUS.md` (create it if missing, one line per phase with date + done/not done). Work only on the current phase. Do not start phase N+1 until phase N's "done" line is true.

| Phase | Deliverable | Done when |
|---|---|---|
| 0 | repos, Compose, stub graph, SSE endpoint | `curl -N /runs` streams a stub, trace in LangSmith |
| 1 | SQL tool on our own IoT DB, guard, evals | `evals/run_evals.py` ≥ 25/30 |
| 2 | JWT auth, vault, `/connections`, then frontend Part B | second person connects a DB without help |
| 3 | ~~web tool (Playwright)~~ | descoped 2026-09-15: the database is the only live source, see `docs/STATUS.md` |
| 4 | Redis workers, limits, usage, Docker deploy (Docker on VPS/CI only) | killing a worker mid-run gives a clean `error` event |
| 5 | file tool (DuckDB), charts | spreadsheet-only customer gets value |
| 6 | billing | paid plan sets `daily_token_budget` |

## 3. Commands

### Local environment — Windows, NO Docker

Docker is **not installed** on the dev machine and is not required until deployment (it runs on the VPS / CI only). Do not run `docker compose` locally and do not suggest installing Docker Desktop. Local infra is one native Postgres 16 server on `localhost:5432` (managed via pgAdmin) with three databases:

| Purpose | Database | User / password | Manual section |
|---|---|---|---|
| App DB (ours, Alembic) | `analyst` | `app` / `app` | 5.1–5.3 |
| Checkpoint DB (LangGraph) | `checkpoints` | `ckpt` / `ckpt` | 5.4 |
| Demo customer DB (seeded) | `demo` | `analyst_ro` / `ro` (read-only) | 5.5 |

Since 2026-09-19 the running app keeps its App DB and Checkpoint DB on **Supabase** instead: the `analyst` and `checkpoints` schemas of the project's database, each owned by its own role (`analyst_app`, `analyst_ckpt`) whose `search_path` is that schema, reached through the session pooler because the direct host is IPv6 only. `scripts/bootstrap_supabase.sql` sets it up and says how to create the tables. Neither schema is exposed through the Data API. The demo customer database stays local, and so do `analyst` and `checkpoints` for the test suite: `tests/conftest.py` sets its own `APP_DB_URL` and `CHECKPOINT_DB_URL`, so `.env` pointing at Supabase never sends the integration suite's `DELETE FROM` there — unless those two are exported in your shell.

```
APP_DB_URL=postgresql+psycopg://analyst_app.<ref>:<pw>@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres?sslmode=require
CHECKPOINT_DB_URL=postgresql://analyst_ckpt.<ref>:<pw>@aws-0-ap-southeast-2.pooler.supabase.com:5432/postgres?sslmode=require
# local, and what the tests use (the manual's 5433/5434/5435 are the Compose ports — ignore them locally):
# APP_DB_URL=postgresql+psycopg://app:app@localhost:5432/analyst
# CHECKPOINT_DB_URL=postgresql://ckpt:ckpt@localhost:5432/checkpoints
# demo connection DSN: postgresql+psycopg://analyst_ro:ro@localhost:5432/demo
```

Redis is **Memurai Developer 4.1.2**, installed and running as a Windows service on 6379. `winget install Memurai.MemuraiDeveloper` fails with MSI 1603 and `SFXCA: Failed to create temp directory. Error code 5` even elevated; download the MSI and run `msiexec /i` directly instead. Any code path that needs Redis still sits behind `QUEUE_ENABLED`, which defaults to off.

`docker-compose.dev.yml` stays in the repo for CI and other developers — keep it in sync with these three databases, but never assume it is running.

### analyst-agent (PowerShell)
```powershell
.\.venv\Scripts\activate
# one-time local DB setup (run once; needs the postgres superuser password)
psql -U postgres -c "CREATE USER app WITH PASSWORD 'app'; CREATE DATABASE analyst OWNER app;"
psql -U postgres -c "CREATE USER ckpt WITH PASSWORD 'ckpt'; CREATE DATABASE checkpoints OWNER ckpt;"
psql -U postgres -c "CREATE USER demo WITH PASSWORD 'demo'; CREATE DATABASE demo OWNER demo;"
psql -U postgres -d demo -f scripts\demo_customer.sql
psql -U analyst_ro -d demo -c "delete from dealers"      # MUST fail: read-only transaction

uvicorn app.main:app --reload --port 8000
uvicorn app.database_mcp:app --port 8001         # the database MCP server; the API will not boot without it
alembic revision --autogenerate -m "msg"; alembic upgrade head
pytest -m "not integration"                           # fast, no DB
pytest -m integration                                 # needs the three local databases above
ruff check app tests; ruff format app tests
$env:TOKEN="..."; $env:CONN="..."; python evals/run_evals.py   # live gate, >= 80% or not done
python evals/recorded.py --record --only 0-9    # capture the model; the free tier is 20/day
python evals/recorded.py --replay               # rerun the suite offline, no API calls
$env:MAX_RUNS_PER_MINUTE="100"                  # a suite trips the per-tenant rate limit
pip-compile --extra dev -o requirements.lock pyproject.toml     # after any dependency change
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

Use `127.0.0.1` in `REDIS_URL`, never `localhost`. Memurai binds IPv4 only while `localhost`
resolves to `::1` first, so a client spends its whole connect timeout on IPv6 and fails, while
`memurai-cli ping` answers normally and makes it look like an application bug.

Phase 4's done-line is one command, and it starts and stops its own server and worker:

```powershell
python scripts/check_killed_worker.py
```

It kills the worker mid-run and asserts the client gets exactly one `error` event and the run
row is not left `running`. Read its docstring before changing it: there are two ways to make it
pass without testing anything.

### analyst-web
```bash
pnpm dev
pnpm gen:agent        # regenerate src/lib/agent/openapi.d.ts — run after any agent API change
pnpm lint && pnpm vitest run --coverage
pnpm playwright test  # needs agent + local Postgres + pnpm dev running
```

## 4. Architecture you must preserve

```
create_agent:  model  <-->  tools        (loop until the model stops calling tools)
                              |
                              +-- query_database  -> sql_guard -> connector (read-only)
                                    described from, and allowed only, the connection's chosen tables
                                       Postgres -> MCP server -> customer DB
                                       file     -> DuckDB, in process
```

The model chooses whether to call a tool, which replaces the hand-written router. The guard
runs inside the tool, so no model-issued SQL can reach a database unguarded. The loop is
bounded by `recursion_limit()`, derived from `max_sql_retries`.

- `app/api/` = HTTP only. `app/services/` = business rules. `app/agent/` = LangGraph. `app/connectors/` = customer data sources. `app/security/` = Supabase token verification + Fernet vault. Nothing imports upward.
- `app/agent/nodes/sql_guard.py` is pure code (sqlglot). **It must never call a model.** SELECT only, one statement, `public` (or DuckDB's `main`) only, table allowlist from the tables chosen for the connection, LIMIT injected, forbidden ops and table-reading functions rejected.
- Table structure is split by job. `app/catalog/` holds its shape (`types.py`) and how tables join (`relationships.py`) and imports nothing from `app`; `app/connectors/pg_catalog.py` and `duckdb.py` read it; `app/services/tables.py` stores it for the chosen tables only; `app/agent/schema_context.py` writes it into the query tool's description. Columns, keys and a size bucket are stored and shown to the model. A row never is.
- `app/security/vault.py` is the only module that sees plaintext credentials. `decrypt()` is called from `app/database_mcp.py` for a database; a dataset's files are rows, not a secret. The API process never decrypts a Postgres DSN. No API response ever contains `secret_enc`, `dsn`, `password`.
- A database is reached only through the MCP server, which runs as its own process because it is the only thing holding a decrypted DSN. It exposes the `SqlConnector` protocol as four tools, and `app/connectors/mcp.py` is the client. All three read-only layers live there with it; `app/agent/tools.py` guards before calling anyway, and the server guards regardless of who called.
- Every function under `connectors/` and `agent/` takes `tenant_id`. No default tenant. Checkpointer thread ids are `f"{tenant_id}:{thread_id}"`.
- Three databases, never confused: App DB (ours, Alembic), Checkpoint DB (LangGraph-managed, disposable), Customer DB (theirs, read-only role, never migrated, never written).
- Frontend: Supabase is called only from the server, with the publishable key; no service-role key or signing secret exists in the frontend. `src/lib/agent/` is the single boundary to the agent. `hooks/useRun.ts` is a state machine driven only by SSE events.

## 5. The SSE contract (frozen — do not change without updating both repos in the same PR)

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

## 6. Hard rules

1. Every LLM call has a Pydantic output schema or a single-string contract. No regex parsing of model output.
2. Every phase adds cases to `evals/golden_sql.yaml`. A PR that lowers the eval pass rate is not merged.
3. `tenant_id` is required, never optional, never inferred from anything but the account `current_tenant` resolves from a verified Supabase token.
4. Customer DB access is read-only at three layers: role (`default_transaction_read_only=on`), connector (`connect_args`), guard (SELECT only). Verify with a DELETE that must fail.
5. Do not add Redis/queue before phase 4. Do not add a second DB connector before a paying customer asks.
5a. Do not require Docker for local development. Anything that only works inside a container belongs in CI or on the VPS.
6. Keep the graph in Python. If heavy analytics is needed, add a tool, not a second orchestrator.
7. Do not build a "quick UI to test the backend". `curl -N` and `evals/run_evals.py` are the UI until phase 2 is done.
8. Never commit `.env`, `sessions/`, `requirements.lock` drift without the matching `pyproject.toml` change, or generated `openapi.d.ts` that doesn't match a running agent.

## 7. Conventions

- Python: ruff (line 100), type hints everywhere, `structlog` with `tenant_id`/`run_id` bound in contextvars, domain errors from `app/services/errors.py` (never raise `HTTPException` outside `app/api/`).
- TypeScript: strict, zod at every boundary (env, forms, route bodies), no `any`, server-only secrets never imported into client components.
- Tests: unit tests script the LLM (see `tests/unit/test_agent.py`); integration tests are marked `integration` and need the three local Postgres databases (Compose in CI only). Coverage floors: 85% `sql_guard.py` + `security/`, 70% overall; 90% `src/lib/agent/`, 80% `src/hooks/`.
- Commits: `feat(agent): ...`, `fix(web): ...`, `chore: ...`. One phase item per PR.
- Prompts live only in `app/agent/prompts.py`. Change a prompt → run evals → paste before/after pass rate in the PR.

## 8. Definition of done for any task

- [ ] Code + tests pass locally (`pytest` / `vitest`)
- [ ] `ruff` / `pnpm lint` clean
- [ ] If the agent API changed: `pnpm gen:agent` run, web builds
- [ ] If prompts or guard changed: evals run, pass rate reported
- [ ] Checkpoint from the manual for that section executed and its expected output observed
- [ ] `docs/STATUS.md` updated

## 9. When unsure

- Read the matching manual section before inventing a new approach.
- Prefer the smaller change that keeps the graph shape in section 4.
- If a request would weaken any hard rule in section 6, stop and ask Apoorv instead of complying.

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agent.graph import build_graph
from app.api.schemas import RunCreate
from app.config import get_settings
from app.connectors.base import Connector
from app.connectors.registry import connector_for
from app.db.models import Connection, Run
from app.logging import log
from app.security.auth import TenantContext
from app.services import connections as conn_svc
from app.services.errors import BudgetExceeded

STAGES = {"router", "sql_gen", "sql_guard", "db_exec", "web_tool", "answer"}
SCHEMA_CACHE_TTL = timedelta(hours=6)


@dataclass(frozen=True)
class PreparedRun:
    run: Run
    connector: Connector
    schema: dict


def _tokens_today(db: Session, tenant_id: str) -> int:
    since = datetime.now(UTC) - timedelta(days=1)
    return (
        db.query(func.coalesce(func.sum(Run.prompt_tokens + Run.completion_tokens), 0))
        .filter(Run.tenant_id == tenant_id, Run.created_at >= since)
        .scalar()
    )


def _refresh_schema_cache(db: Session, conn: Connection, connector: Connector) -> dict:
    stale = conn.schema_cached_at is None or (
        datetime.now(UTC) - conn.schema_cached_at > SCHEMA_CACHE_TTL
    )
    if conn.schema_cache is None or stale:
        conn.schema_cache = connector.describe_schema()
        conn.schema_cached_at = datetime.now(UTC)
        db.commit()
    return conn.schema_cache


def prepare_run(db: Session, ctx: TenantContext, body: RunCreate) -> PreparedRun:
    """Everything that can still fail as a plain HTTP status, done before the stream opens.

    Once `EventSourceResponse` starts writing, the status line is already sent, so a budget or
    not-found error raised later could only appear as an SSE `error` event.
    """
    tenant = conn_svc.ensure_tenant(db, ctx.tenant_id)
    if _tokens_today(db, tenant.id) >= tenant.daily_token_budget:
        raise BudgetExceeded("daily token budget exhausted")

    conn = conn_svc.get_connection(db, ctx.tenant_id, body.connection_id)
    connector = connector_for(conn)
    schema = _refresh_schema_cache(db, conn, connector)

    run = Run(
        tenant_id=ctx.tenant_id,
        connection_id=conn.id,
        thread_id=body.thread_id,
        question=body.question,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return PreparedRun(run=run, connector=connector, schema=schema)


async def stream_run(
    db: Session, ctx: TenantContext, body: RunCreate, prepared: PreparedRun
) -> AsyncIterator[dict]:
    s = get_settings()
    run = prepared.run
    # The SSE generator runs in its own task, so the auth dependency's binding does not reach it.
    structlog.contextvars.bind_contextvars(tenant_id=ctx.tenant_id, run_id=run.id)
    log.info("run.start", connection_id=run.connection_id, thread_id=body.thread_id)

    usage = UsageMetadataCallbackHandler()
    t0 = time.perf_counter()
    final: dict = {}

    try:
        with PostgresSaver.from_conn_string(str(s.checkpoint_db_url)) as saver:
            graph = build_graph(prepared.connector, checkpointer=saver)
            config = {
                "configurable": {"thread_id": f"{ctx.tenant_id}:{body.thread_id}"},
                "callbacks": [usage],
                "metadata": {"tenant_id": ctx.tenant_id, "run_id": run.id},
            }
            inputs = {
                "tenant_id": ctx.tenant_id,
                "connection_id": run.connection_id,
                "question": body.question,
                "schema": prepared.schema,
                "retries": 0,
            }
            # Synchronous, so it holds the event loop for the length of the run. Acceptable
            # through phase 2; phase 4 moves this body into an arq worker.
            for event in graph.stream(inputs, config=config, stream_mode="updates"):
                node, update = next(iter(event.items()))
                if node in STAGES:
                    yield {"type": "status", "data": {"stage": node}}
                if node == "sql_guard" and update.get("guard_error") is None:
                    yield {"type": "sql", "data": {"sql": update["sql"]}}
                if node in ("db_exec", "web_tool") and "rows" in update:
                    yield {
                        "type": "rows",
                        "data": {
                            "columns": update["columns"],
                            "rows": update["rows"],
                            "truncated": update["truncated"],
                        },
                    }
                if node == "answer" and "answer" in update:
                    yield {"type": "token", "data": {"text": update["answer"]}}
                final.update(update)

        run.status = "error" if final.get("error") else "done"
    except Exception as e:
        log.exception("run.failed")
        run.status, run.error = "error", str(e)
        yield {"type": "error", "data": {"message": "run failed; see logs"}}
    finally:
        run.duration_ms = int((time.perf_counter() - t0) * 1000)
        run.tool, run.sql = final.get("tool"), final.get("sql")
        run.rows_returned = len(final.get("rows", []))
        totals = usage.usage_metadata.get(s.openrouter_model, {})
        run.prompt_tokens = totals.get("input_tokens", 0)
        run.completion_tokens = totals.get("output_tokens", 0)
        db.commit()
        log.info("run.end", status=run.status, ms=run.duration_ms)

    if run.status == "done":
        yield {"type": "done", "data": {"run_id": run.id, "duration_ms": run.duration_ms}}

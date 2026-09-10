import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agent.graph import build_agent, recursion_limit
from app.api.schemas import RunCreate
from app.config import get_settings
from app.connectors.base import Connector
from app.connectors.registry import connector_for
from app.db.models import Connection, Run
from app.logging import log
from app.security.auth import TenantContext
from app.services import connections as conn_svc
from app.services.errors import BudgetExceeded

SCHEMA_CACHE_TTL = timedelta(hours=6)


@dataclass(frozen=True)
class PreparedRun:
    run: Run
    connector: Connector
    schema: dict


@dataclass
class RunOutcome:
    """What the Run row needs, accumulated as the agent streams."""

    tool: str | None = None
    sql: str | None = None
    rows: list = field(default_factory=list)
    answer: str = ""


class EventTranslator:
    """Maps the agent's `model` and `tools` steps onto the frozen SSE contract.

    `create_agent` has two nodes, but the contract names five stages, so each step is reported
    as the stage it actually performs: the first model call is the routing decision, a model
    call that emits a tool call is generation, and the tool guards then executes.
    """

    def __init__(self, outcome: RunOutcome):
        self.outcome = outcome
        self._routed = False

    def for_message(self, node: str, message: Any) -> Iterator[dict]:
        if node == "model" and isinstance(message, AIMessage):
            yield from self._for_model(message)
        elif node == "tools" and isinstance(message, ToolMessage):
            yield from self._for_tool(message)

    def _for_model(self, message: AIMessage) -> Iterator[dict]:
        if not self._routed:
            self._routed = True
            yield {"type": "status", "data": {"stage": "router"}}

        if message.tool_calls:
            self.outcome.tool = "sql"
            yield {"type": "status", "data": {"stage": "sql_gen"}}
        elif message.content:
            self.outcome.tool = self.outcome.tool or "clarify"
            self.outcome.answer = str(message.content)
            yield {"type": "status", "data": {"stage": "answer"}}
            yield {"type": "token", "data": {"text": self.outcome.answer}}

    def _for_tool(self, message: ToolMessage) -> Iterator[dict]:
        result = message.artifact or {}
        yield {"type": "status", "data": {"stage": "sql_guard"}}
        if result.get("error"):
            return  # rejected, so no SQL was run and the model will be asked to correct it

        self.outcome.sql = result["sql"]
        self.outcome.rows = result["rows"]
        yield {"type": "sql", "data": {"sql": result["sql"]}}
        yield {"type": "status", "data": {"stage": "db_exec"}}
        yield {
            "type": "rows",
            "data": {
                "columns": result["columns"],
                "rows": result["rows"],
                "truncated": result["truncated"],
            },
        }


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

    Once the response starts writing, the status line is already sent, so a budget or
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
    outcome = RunOutcome()
    translator = EventTranslator(outcome)
    t0 = time.perf_counter()

    try:
        with PostgresSaver.from_conn_string(str(s.checkpoint_db_url)) as saver:
            agent = build_agent(prepared.connector, prepared.schema, checkpointer=saver)
            config = {
                "configurable": {"thread_id": f"{ctx.tenant_id}:{body.thread_id}"},
                "callbacks": [usage],
                "metadata": {"tenant_id": ctx.tenant_id, "run_id": run.id},
                "recursion_limit": recursion_limit(),
            }
            # Synchronous, so it holds the event loop for the length of a run. Acceptable
            # through phase 2; phase 4 moves this body into an arq task.
            for chunk in agent.stream(
                {"messages": [("user", body.question)]}, config=config, stream_mode="updates"
            ):
                for node, update in chunk.items():
                    for message in (update or {}).get("messages", []):
                        for event in translator.for_message(node, message):
                            yield event
        run.status = "done"
    except Exception as e:
        log.exception("run.failed")
        run.status, run.error = "error", str(e)
        yield {"type": "error", "data": {"message": "run failed; see logs"}}
    finally:
        run.duration_ms = int((time.perf_counter() - t0) * 1000)
        run.tool, run.sql = outcome.tool, outcome.sql
        run.rows_returned = len(outcome.rows)
        totals = usage.usage_metadata.get(s.openrouter_model, {})
        run.prompt_tokens = totals.get("input_tokens", 0)
        run.completion_tokens = totals.get("output_tokens", 0)
        db.commit()
        log.info("run.end", status=run.status, ms=run.duration_ms)

    if run.status == "done":
        yield {"type": "done", "data": {"run_id": run.id, "duration_ms": run.duration_ms}}

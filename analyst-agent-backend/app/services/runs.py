import asyncio
import base64
import json
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.errors import GraphRecursionError
from sqlalchemy import func, select, update
from sqlalchemy import tuple_ as sa_tuple
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session

from app import queue
from app.agent.graph import build_agent, recursion_limit
from app.api.schemas import RunCreate
from app.catalog.types import Catalog
from app.config import get_settings
from app.connectors.base import SqlConnector
from app.connectors.registry import connector_for
from app.db.models import Connection, Run, Tenant
from app.db.session import SessionLocal
from app.logging import log
from app.security.auth import TenantContext
from app.services import connections as conn_svc
from app.services import tables as tables_svc
from app.services.charts import infer_chart
from app.services.errors import BudgetExceeded, DomainError, NotFound, RateLimited

Emit = Callable[[dict], None]


@dataclass(frozen=True)
class PreparedRun:
    run: Run
    connector: SqlConnector
    catalog: Catalog


@dataclass
class RunOutcome:
    """What the Run row needs, accumulated as the agent streams."""

    tool: str | None = None
    sql: str | None = None
    rows: list = field(default_factory=list)
    chart: dict | None = None
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
            return

        # Gemini 3 returns a list of content blocks rather than a string, so read `.text`,
        # which flattens both shapes. `.content` would serialise a Python repr into the stream.
        answer = message.text
        if answer:
            self.outcome.tool = self.outcome.tool or "clarify"
            self.outcome.answer = answer
            yield {"type": "status", "data": {"stage": "answer"}}
            yield {"type": "token", "data": {"text": answer}}

    def _for_tool(self, message: ToolMessage) -> Iterator[dict]:
        result = message.artifact or {}
        if not result:
            return  # an unknown tool name or an exception escaping one carries no artifact

        yield {"type": "status", "data": {"stage": "sql_guard"}}
        if result.get("error"):
            return  # rejected, so no SQL was run and the model will be asked to correct it

        self.outcome.sql = result["sql"]
        yield {"type": "sql", "data": {"sql": result["sql"]}}
        yield {"type": "status", "data": {"stage": "db_exec"}}
        yield from self._rows(result)

    def _rows(self, result: dict) -> Iterator[dict]:
        self.outcome.rows = result["rows"]
        yield {
            "type": "rows",
            "data": {
                "columns": result["columns"],
                "rows": result["rows"],
                "truncated": result["truncated"],
            },
        }
        # Emitted per tool call, so a second query supersedes the first exactly as `sql` and
        # `rows` already do. `chart` is a payload rather than a stage, so the frozen stage list
        # is unchanged.
        chart = infer_chart(result["columns"], result["rows"], result["truncated"])
        if chart:
            self.outcome.chart = chart
            yield {"type": "chart", "data": chart}


def sse_frame(event: dict) -> dict[str, str]:
    """The one place a run's event becomes bytes.

    This is simultaneously a valid Redis stream field map and exactly what EventSourceResponse
    consumes, so the in-process and queued paths cannot drift into producing different bytes.
    `default=str` keeps Decimal, date, datetime and UUID losslessly encodable: JSON has no type
    for them, and float() would quietly lose precision on money.
    """
    return {"event": event["type"], "data": json.dumps(event["data"], default=str)}


@dataclass(frozen=True)
class TenantUsage:
    tokens_last_24h: int
    runs_last_24h: int
    runs_last_minute: int
    runs_in_flight: int


def _tenant_usage(db: Session, tenant_id: str) -> TenantUsage:
    """One range scan on (tenant_id, created_at) answering every limit at once."""
    now = datetime.now(UTC)
    row = db.execute(
        select(
            func.coalesce(func.sum(Run.prompt_tokens + Run.completion_tokens), 0),
            func.count(),
            func.count().filter(Run.created_at >= now - timedelta(minutes=1)),
            func.count().filter(Run.status == "running"),
        ).where(Run.tenant_id == tenant_id, Run.created_at >= now - timedelta(days=1))
    ).one()
    return TenantUsage(*row)


def check_limits(db: Session, tenant: Tenant) -> None:
    """Budget first: it is the commercial limit, and the other two are only throttles."""
    s = get_settings()
    usage = _tenant_usage(db, tenant.id)
    if usage.tokens_last_24h >= tenant.daily_token_budget:
        raise BudgetExceeded("daily token budget exhausted")
    if usage.runs_last_minute >= s.max_runs_per_minute:
        raise RateLimited("too many runs in the last minute")
    if usage.runs_in_flight >= s.max_concurrent_runs:
        raise RateLimited("too many runs already in progress")


def finish_run(db: Session, run_id: str, **values: Any) -> bool:
    """Settle a run. First writer wins.

    With a worker there are two possible writers: the thread executing the run, and whichever
    consumer decides the run is dead. `WHERE status = 'running'` makes that a race nobody loses
    data to, with no locking. Assigning to the ORM object instead would write every dirty
    column and let a late-finishing orphan overwrite an error already recorded.
    """
    result = db.execute(
        update(Run).where(Run.id == run_id, Run.status == "running").values(**values)
    )
    db.commit()
    return result.rowcount > 0


def abandon_run(db: Session, run_id: str, message: str) -> None:
    """Safe to call unconditionally on teardown: a run that already finished matches nothing."""
    if finish_run(db, run_id, status="error", error=message):
        log.info("run.abandoned", run_id=run_id, reason=message)


def reap_stale_runs(db: Session) -> int:
    """Rows left `running` by a process that died mid-run.

    Load-bearing rather than tidy: `max_concurrent_runs` counts running rows, so a leaked one
    would permanently consume a tenant's slot.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=get_settings().run_timeout_s)
    result = db.execute(
        update(Run)
        .where(Run.status == "running", Run.created_at < cutoff)
        .values(status="error", error="run did not finish")
    )
    db.commit()
    if result.rowcount:
        log.warning("run.reaped", count=result.rowcount)
    return result.rowcount


async def prepare_run(db: Session, ctx: TenantContext, body: RunCreate) -> PreparedRun:
    """Everything that can still fail as a plain HTTP status, done before the stream opens.

    Once the response starts writing, the status line is already sent, so a budget or
    not-found error raised later could only appear as an SSE `error` event.
    """
    tenant = conn_svc.ensure_tenant(db, ctx.tenant_id)
    check_limits(db, tenant)

    conn = conn_svc.get_connection(db, ctx.tenant_id, body.connection_id)
    connector = connector_for(conn)
    catalog = await tables_svc.load_for_run(db, conn, connector)

    run = Run(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        connection_id=conn.id,
        thread_id=body.thread_id,
        question=body.question,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    if get_settings().queue_enabled:
        await queue.pool().enqueue_job("run_question", run.id, _job_id=run.id)

    return PreparedRun(run=run, connector=connector, catalog=catalog)


def execute_run(
    db: Session,
    run: Run,
    connector: SqlConnector,
    catalog: Catalog,
    emit: Emit,
) -> None:
    """Drive the agent and report what it does. Synchronous, because `agent.stream` is.

    Both transports call this on a worker thread, so it owns the session it is handed: a
    SQLAlchemy Session is not thread-safe and the request's session belongs to the request.
    It never mutates `run`; it settles the row with one guarded UPDATE.
    """
    s = get_settings()
    structlog.contextvars.bind_contextvars(tenant_id=run.tenant_id, run_id=run.id)
    log.info("run.start", connection_id=run.connection_id, thread_id=run.thread_id)

    usage = UsageMetadataCallbackHandler()
    outcome = RunOutcome()
    translator = EventTranslator(outcome)
    t0 = time.perf_counter()
    status, error = "done", None

    try:
        with PostgresSaver.from_conn_string(str(s.checkpoint_db_url)) as saver:
            agent = build_agent(connector, catalog, checkpointer=saver)
            config = {
                "configurable": {"thread_id": f"{run.tenant_id}:{run.thread_id}"},
                "callbacks": [usage],
                "metadata": {"tenant_id": run.tenant_id, "run_id": run.id},
                "recursion_limit": recursion_limit(),
            }
            for chunk in agent.stream(
                {"messages": [("user", run.question)]}, config=config, stream_mode="updates"
            ):
                for node, update_ in chunk.items():
                    for message in (update_ or {}).get("messages", []):
                        for event in translator.for_message(node, message):
                            emit(event)
    except GraphRecursionError as e:
        # The model kept calling tools without settling on an answer.
        log.warning("run.exhausted", limit=recursion_limit())
        status, error = "error", str(e)
        emit(
            {
                "type": "error",
                "data": {
                    "message": "gave up after too many query attempts; try a narrower question"
                },
            }
        )
    except Exception as e:
        log.exception("run.failed")
        status, error = "error", str(e)
        emit({"type": "error", "data": {"message": "run failed; see logs"}})

    duration_ms = int((time.perf_counter() - t0) * 1000)
    # The provider reports the model it actually resolved, which is not always the configured
    # name. Keying on that name recorded zero tokens whenever the two differed, and the daily
    # budget is enforced from exactly this number.
    totals = list(usage.usage_metadata.values())
    finish_run(
        db,
        run.id,
        status=status,
        error=error,
        duration_ms=duration_ms,
        tool=outcome.tool,
        sql=outcome.sql,
        # `or None`, so a run that produced no narrative reads as "not recorded" rather than
        # as an empty answer, which is the same thing every pre-existing run says.
        answer=outcome.answer or None,
        rows_returned=len(outcome.rows),
        chart=outcome.chart,
        model=next(iter(usage.usage_metadata), None),
        prompt_tokens=sum(t.get("input_tokens", 0) for t in totals),
        completion_tokens=sum(t.get("output_tokens", 0) for t in totals),
    )
    log.info("run.end", status=status, ms=duration_ms)

    if status == "done":
        emit({"type": "done", "data": {"run_id": run.id, "duration_ms": duration_ms}})


async def _stream_inline(prepared: PreparedRun) -> AsyncIterator[dict[str, str]]:
    """Run in this process, on a worker thread so the event loop stays free.

    Before this the agent ran on the loop itself, which meant a client disconnect could not be
    observed and keep-alive pings never fired for the length of a run.
    """
    frames: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    run = prepared.run

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(frames.put_nowait, sse_frame(event))

    def work() -> None:
        db = SessionLocal()
        try:
            execute_run(db, run, prepared.connector, prepared.catalog, emit)
        finally:
            db.close()
            loop.call_soon_threadsafe(frames.put_nowait, None)

    task = asyncio.create_task(asyncio.to_thread(work))
    try:
        while (frame := await frames.get()) is not None:
            yield frame
    finally:
        await task


async def _stream_queued(run_id: str) -> AsyncIterator[dict[str, str]]:
    """Read what the worker publishes.

    A worker that stops proving it is alive ends the stream with one error frame rather than
    leaving the client hanging.
    """
    try:
        async for frame in queue.consume(queue.pool(), run_id):
            yield frame
    except TimeoutError:
        db = SessionLocal()
        try:
            abandon_run(db, run_id, "worker lost")
        finally:
            db.close()
        yield sse_frame({"type": "error", "data": {"message": "the run stopped responding"}})


async def stream_run(
    db: Session, ctx: TenantContext, prepared: PreparedRun
) -> AsyncIterator[dict[str, str]]:
    run_id = prepared.run.id
    queued = get_settings().queue_enabled
    stream = _stream_queued(run_id) if queued else _stream_inline(prepared)
    try:
        async for frame in stream:
            yield frame
    finally:
        # A disconnect would otherwise leave the row `running` for ever. Harmless once the run
        # has finished, because the guarded update matches nothing.
        abandon_run(db, run_id, "client disconnected")
        if queued:
            await queue.request_abort(queue.pool(), run_id)


def get_run(db: Session, tenant_id: str, run_id: str) -> Run:
    run = db.get(Run, run_id)
    if run is None or run.tenant_id != tenant_id:
        raise NotFound("run not found")  # 404 for both, so existence does not leak
    return run


TITLE_CHARS = 120


def _encode_cursor(run: Run) -> str:
    return base64.urlsafe_b64encode(f"{run.created_at.isoformat()}|{run.id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts, _, run_id = raw.partition("|")
        return datetime.fromisoformat(ts), run_id
    except (ValueError, UnicodeDecodeError) as e:
        raise DomainError("that page cursor is not valid") from e


def list_runs(
    db: Session,
    tenant_id: str,
    *,
    thread_id: str | None = None,
    status: str | None = None,
    connection_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """One page of a tenant's history, newest first.

    Keyset rather than offset: runs insert at the head of this ordering, so an offset page
    would repeat and skip rows while someone is reading. The connection name comes from a join
    in this same statement, never from `run.connection.name` per row.
    """
    stmt = (
        select(Run, Connection.name)
        .join(Connection, Connection.id == Run.connection_id, isouter=True)
        .where(Run.tenant_id == tenant_id)
        .order_by(Run.created_at.desc(), Run.id.desc())
        .limit(limit + 1)  # one extra, purely to learn whether another page exists
    )
    if thread_id:
        stmt = stmt.where(Run.thread_id == thread_id)
    if status:
        stmt = stmt.where(Run.status == status)
    if connection_id:
        stmt = stmt.where(Run.connection_id == connection_id)
    if cursor:
        ts, run_id = _decode_cursor(cursor)
        stmt = stmt.where(sa_tuple(Run.created_at, Run.id) < sa_tuple(ts, run_id))

    rows = db.execute(stmt).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        {
            "id": run.id,
            "thread_id": run.thread_id,
            "question": run.question,
            "status": run.status,
            "tool": run.tool,
            "connection_id": run.connection_id,
            "connection_name": conn_name,
            "rows_returned": run.rows_returned,
            "duration_ms": run.duration_ms,
            "created_at": run.created_at,
            "has_sql": run.sql is not None,
            "has_answer": run.answer is not None,
        }
        for run, conn_name in rows
    ]
    next_cursor = _encode_cursor(rows[-1][0]) if has_more and rows else None
    return items, next_cursor


def list_threads(db: Session, tenant_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Every conversation the tenant has had, newest activity first.

    One statement, not a query per thread: `array_agg` with an ordering picks the first
    question as the title and the newest row's status, which is what the sidebar shows.
    """
    first_question = func.array_agg(aggregate_order_by(Run.question, Run.created_at.asc()))[1]
    last_status = func.array_agg(aggregate_order_by(Run.status, Run.created_at.desc()))[1]
    last_connection = func.array_agg(aggregate_order_by(Run.connection_id, Run.created_at.desc()))[
        1
    ]

    rows = db.execute(
        select(
            Run.thread_id,
            func.count().label("run_count"),
            func.max(Run.created_at).label("last_run_at"),
            first_question,
            last_status,
            last_connection,
        )
        .where(Run.tenant_id == tenant_id)
        .group_by(Run.thread_id)
        .order_by(func.max(Run.created_at).desc())
        .limit(limit)
    ).all()

    return [
        {
            "thread_id": thread_id,
            "title": (question or "")[:TITLE_CHARS],
            "run_count": run_count,
            "last_run_at": last_run_at,
            "last_status": status,
            "connection_id": connection_id,
        }
        for thread_id, run_count, last_run_at, question, status, connection_id in rows
    ]


def usage_summary(db: Session, tenant: Tenant, days: int) -> dict[str, Any]:
    """Per-day totals plus the rolling figure the 429 actually refers to.

    Reporting only calendar days would ship as "my usage says zero but I am getting 429s",
    because the budget is enforced over a rolling 24 hours. `date_trunc` on a timestamptz uses
    the session time zone, so the conversion to UTC is explicit: a native Windows Postgres has
    it set to the machine's zone and would silently bucket by local day.
    """
    day = func.date_trunc("day", func.timezone("UTC", Run.created_at))
    rows = db.execute(
        select(
            day.label("day"),
            func.count(),
            func.coalesce(func.sum(Run.prompt_tokens), 0),
            func.coalesce(func.sum(Run.completion_tokens), 0),
            func.coalesce(func.sum(Run.rows_returned), 0),
            func.count().filter(Run.status == "error"),
        )
        .where(
            Run.tenant_id == tenant.id,
            Run.created_at >= datetime.now(UTC) - timedelta(days=days),
        )
        .group_by(day)
        .order_by(day)
    ).all()

    usage = _tenant_usage(db, tenant.id)
    return {
        "daily_token_budget": tenant.daily_token_budget,
        "tokens_last_24h": usage.tokens_last_24h,
        "runs_last_24h": usage.runs_last_24h,
        "days": [
            {
                "day": d.date(),
                "runs": runs,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "rows_returned": returned,
                "errors": errors,
            }
            for d, runs, prompt, completion, returned, errors in rows
        ],
    }

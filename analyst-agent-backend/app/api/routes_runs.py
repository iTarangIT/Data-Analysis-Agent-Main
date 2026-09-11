from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import current_tenant
from app.api.schemas import RunCreate, RunOut, RunPage, ThreadOut
from app.db.session import get_db
from app.security.auth import TenantContext
from app.services import runs as svc

router = APIRouter()


@router.post("")
async def create_run(
    body: RunCreate,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    # Runs before the response starts, so a missing connection, an exhausted budget or a rate
    # limit still surfaces as a real HTTP status rather than an SSE error event.
    prepared = await svc.prepare_run(db, ctx, body)
    return EventSourceResponse(svc.stream_run(db, ctx, prepared))


@router.get("", response_model=RunPage)
def list_runs(
    thread_id: str | None = None,
    status: Literal["running", "done", "error"] | None = None,
    connection_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> RunPage:
    """A page of past runs, newest first.

    Carries no result rows, and never will: `runs` records how many rows came back, not what
    they were. Keeping a customer's result set in this database is exactly what
    SCHEMA_SAMPLE_ROWS=0 exists to prevent. A past run is re-read by running it again.
    """
    items, next_cursor = svc.list_runs(
        db,
        ctx.tenant_id,
        thread_id=thread_id,
        status=status,
        connection_id=connection_id,
        limit=limit,
        cursor=cursor,
    )
    return RunPage(items=items, next_cursor=next_cursor)


# Declared before /{run_id}, or FastAPI matches "threads" as a run id and this 404s.
@router.get("/threads", response_model=list[ThreadOut])
def list_threads(
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> list[ThreadOut]:
    """Every conversation, for the sidebar."""
    return [ThreadOut(**t) for t in svc.list_threads(db, ctx.tenant_id, limit=limit)]


@router.get("/{run_id}", response_model=RunOut)
def read_run(
    run_id: str,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> RunOut:
    """How a client that lost the stream learns the outcome, which a worker makes possible."""
    return RunOut.model_validate(svc.get_run(db, ctx.tenant_id, run_id), from_attributes=True)

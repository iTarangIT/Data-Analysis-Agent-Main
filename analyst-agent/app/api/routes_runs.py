from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import current_tenant
from app.api.schemas import RunCreate, RunOut
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


@router.get("/{run_id}", response_model=RunOut)
def read_run(
    run_id: str,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> RunOut:
    """How a client that lost the stream learns the outcome, which a worker makes possible."""
    return RunOut.model_validate(svc.get_run(db, ctx.tenant_id, run_id), from_attributes=True)

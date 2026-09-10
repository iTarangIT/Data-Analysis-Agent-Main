import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import current_tenant
from app.api.schemas import RunCreate
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
    # Runs before the response starts, so a missing connection or an exhausted budget still
    # surfaces as a real HTTP status rather than an SSE error event.
    prepared = svc.prepare_run(db, ctx, body)

    async def event_stream():
        async for event in svc.stream_run(db, ctx, body, prepared):
            yield {"event": event["type"], "data": json.dumps(event["data"])}

    return EventSourceResponse(event_stream())

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import current_tenant
from app.api.schemas import ConnectionCreate, ConnectionOut
from app.db.models import Connection
from app.db.session import get_db
from app.security.auth import TenantContext
from app.services import connections as svc

router = APIRouter()


def _out(c: Connection) -> ConnectionOut:
    return ConnectionOut(
        id=c.id, name=c.name, kind=c.kind, has_schema_cache=c.schema_cache is not None
    )


@router.post("", response_model=ConnectionOut, status_code=201)
def create(
    body: ConnectionCreate,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    return _out(svc.create_connection(db, ctx.tenant_id, body.name, body.kind, body.secret))


@router.get("", response_model=list[ConnectionOut])
def list_(
    ctx: TenantContext = Depends(current_tenant), db: Session = Depends(get_db)
) -> list[ConnectionOut]:
    return [_out(c) for c in svc.list_connections(db, ctx.tenant_id)]

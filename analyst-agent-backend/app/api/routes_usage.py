from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_tenant
from app.api.schemas import UsageOut
from app.db.session import get_db
from app.security.auth import TenantContext
from app.services import connections as conn_svc
from app.services import runs as svc

router = APIRouter()


@router.get("", response_model=UsageOut)
def usage(
    days: int = Query(30, ge=1, le=90),
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> UsageOut:
    tenant = conn_svc.ensure_tenant(db, ctx.tenant_id)
    return UsageOut(**svc.usage_summary(db, tenant, days))

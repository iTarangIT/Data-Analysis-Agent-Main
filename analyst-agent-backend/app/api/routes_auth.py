from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import current_identity, current_tenant
from app.api.schemas import ProvisionIn, UserOut
from app.db.models import User
from app.db.session import get_db
from app.security.auth import TenantContext
from app.security.supabase import Identity
from app.services import identity as svc

router = APIRouter()

# Signing up, signing in, refreshing and signing out all happen against Supabase. What is left
# here is who you are in this service, and joining it.


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        tenant_id=user.tenant_id,
        tenant_name=user.tenant.name,
        plan=user.tenant.plan,
        created_at=user.created_at,
    )


@router.get("/me", response_model=UserOut)
def me(ctx: TenantContext = Depends(current_tenant), db: Session = Depends(get_db)) -> UserOut:
    return _user_out(svc.current_user(db, ctx.tenant_id, ctx.user_id))


@router.post("/provision", response_model=UserOut, status_code=201)
def provision(
    body: ProvisionIn,
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db),
) -> UserOut:
    """Create the caller's organisation, the first time they sign in.

    Takes an identity rather than a tenant: until this succeeds there is no tenant to take.
    """
    return _user_out(svc.provision(db, identity, body.tenant_name))

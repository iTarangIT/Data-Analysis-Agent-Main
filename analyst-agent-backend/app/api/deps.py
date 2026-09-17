import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.security.auth import TenantContext
from app.security.supabase import Identity, verify_access_token
from app.services import identity as identity_svc

_bearer = HTTPBearer(auto_error=False)


def current_identity(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Identity:
    """A verified Supabase user, who may not have an account here yet."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        return verify_access_token(creds.credentials)
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from e


def current_tenant(
    identity: Identity = Depends(current_identity),
    db: Session = Depends(get_db),
) -> TenantContext:
    """The tenant a request acts for, read from the account rather than the token.

    A 403 with code `onboarding_required` means signed in but not yet a member of anything.
    """
    user = identity_svc.resolve(db, identity)
    ctx = TenantContext(tenant_id=user.tenant_id, user_id=user.id)
    structlog.contextvars.bind_contextvars(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
    return ctx

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.security.auth import TenantContext, decode_token

_bearer = HTTPBearer(auto_error=False)


def current_tenant(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TenantContext:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        ctx = decode_token(creds.credentials)
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from e

    structlog.contextvars.bind_contextvars(tenant_id=ctx.tenant_id, user_id=ctx.user_id)
    return ctx

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import current_tenant
from app.api.schemas import AuthOut, LoginIn, LogoutIn, RefreshIn, RegisterIn, UserOut
from app.config import get_settings
from app.db.models import User
from app.db.session import get_db
from app.security.auth import TenantContext
from app.services import auth as svc

router = APIRouter()

# Every route here is a plain `def`, so FastAPI runs it in its threadpool. Argon2 costs 50 to
# 100ms by design, and `app.services.runs` already holds the event loop for the length of a
# run; a second blocker on it would stall every other request in the process.


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


def _auth_out(user: User, access: str, refresh: str) -> AuthOut:
    s = get_settings()
    return AuthOut(
        access_token=access,
        expires_in=s.access_token_ttl_minutes * 60,
        refresh_token=refresh,
        refresh_expires_in=s.refresh_token_ttl_days * 86_400,
        user=_user_out(user),
    )


def _client(request: Request) -> dict[str, str | None]:
    """Audit fields only. Behind a proxy these describe the proxy unless it forwards the
    originating address, so nothing may authorise on them."""
    return {
        "user_agent": request.headers.get("user-agent"),
        "ip": request.client.host if request.client else None,
    }


@router.post("/register", response_model=AuthOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)) -> AuthOut:
    """Create an organisation and its first user, who owns it."""
    user, access, refresh = svc.register(
        db,
        email=body.email,
        password=body.password,
        name=body.name,
        tenant_name=body.tenant_name,
        **_client(request),
    )
    return _auth_out(user, access, refresh)


@router.post("/login", response_model=AuthOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)) -> AuthOut:
    user, access, refresh = svc.login(
        db, email=body.email, password=body.password, **_client(request)
    )
    return _auth_out(user, access, refresh)


@router.post("/refresh", response_model=AuthOut)
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)) -> AuthOut:
    """Takes no bearer: the refresh token is itself the credential, and the access token it
    replaces has usually expired by the time this is called."""
    user, access, new_refresh = svc.refresh(
        db, refresh_token=body.refresh_token, **_client(request)
    )
    return _auth_out(user, access, new_refresh)


@router.post("/logout", status_code=204, response_class=Response)
def logout(body: LogoutIn, db: Session = Depends(get_db)) -> Response:
    """Always 204, even for a token that was never real.

    Takes no bearer for the same reason refresh does not: signing out has to work precisely
    when the access token has expired, which is when it matters most.

    Note this cannot revoke an access token, which is stateless and lives for fifteen minutes.
    That short life is the whole reason it is short.
    """
    svc.logout(db, refresh_token=body.refresh_token, all_devices=body.all_devices)
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
def me(ctx: TenantContext = Depends(current_tenant), db: Session = Depends(get_db)) -> UserOut:
    """404 when the token is valid but names no user.

    That is the normal case for the eval harness and the test fixtures, which hand-mint tokens
    for subjects that have no row, so it must stay a clean 404 rather than a 500.
    """
    return _user_out(svc.current_user(db, ctx.tenant_id, ctx.user_id))

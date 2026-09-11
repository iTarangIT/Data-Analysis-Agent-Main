"""Sign-up, sign-in, and refresh-token rotation.

Mints exactly the token shape this service already accepted, so adding real accounts changed
no existing route and invalidated no hand-minted token.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import RefreshToken, Tenant, User
from app.logging import log
from app.security import passwords
from app.security.auth import hash_refresh_token, mint_access_token, new_refresh_token
from app.services.errors import Conflict, Forbidden, NotFound, Unauthorized

# One message for an unknown address, a wrong password and a disabled account. A disabled
# account must be indistinguishable from a wrong password, or the reply enumerates users.
_BAD_CREDENTIALS = "invalid email or password"
_BAD_REFRESH = "invalid or expired refresh token"


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    """Applied identically on register and on login, or the unique index is bypassed and one
    address registers twice in different cases."""
    return email.strip().lower()


def _issue(
    db: Session,
    user: User,
    *,
    family_id: str | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[str, str, RefreshToken]:
    """Mint an access token and a refresh token, recording the refresh token's row."""
    s = get_settings()
    raw = new_refresh_token()
    row = RefreshToken(
        user_id=user.id,
        family_id=family_id or str(uuid.uuid4()),
        token_hash=hash_refresh_token(raw),
        expires_at=_now() + timedelta(days=s.refresh_token_ttl_days),
        user_agent=user_agent[:200] if user_agent else None,
        ip=ip,
    )
    db.add(row)
    return mint_access_token(tenant_id=user.tenant_id, user_id=user.id), raw, row


def register(
    db: Session,
    *,
    email: str,
    password: str,
    name: str | None = None,
    tenant_name: str | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[User, str, str]:
    """Create a tenant and its first user. Returns the user and a fresh token pair."""
    s = get_settings()
    if not s.allow_open_signup:
        raise Forbidden("signups are closed")

    email = normalize_email(email)
    tenant = Tenant(id=str(uuid.uuid4()), name=(tenant_name or email).strip())
    user = User(
        tenant_id=tenant.id,
        email=email,
        password_hash=passwords.hash_password(password),
        name=name,
        role="owner",  # whoever signs up owns the tenant they just created
        last_login_at=_now(),
    )
    db.add(tenant)
    db.add(user)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        # The unique index on email is the authority, not a prior SELECT, which would race.
        raise Conflict("an account with that email already exists") from e

    access, refresh_raw, _ = _issue(db, user, user_agent=user_agent, ip=ip)
    db.commit()
    log.info("auth.register", user_id=user.id, tenant_id=tenant.id)
    return user, access, refresh_raw


def login(
    db: Session,
    *,
    email: str,
    password: str,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[User, str, str]:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))

    if user is None:
        # Hash anyway, so an unregistered address costs the same time as a wrong password.
        passwords.verify(passwords.DUMMY_HASH, password)
        raise Unauthorized(_BAD_CREDENTIALS)
    if not passwords.verify(user.password_hash, password) or not user.is_active:
        raise Unauthorized(_BAD_CREDENTIALS)

    if passwords.needs_rehash(user.password_hash):
        # The only moment the plaintext is in hand, so parameter upgrades happen here or never.
        user.password_hash = passwords.hash_password(password)

    user.last_login_at = _now()
    access, refresh_raw, _ = _issue(db, user, user_agent=user_agent, ip=ip)
    db.commit()
    log.info("auth.login", user_id=user.id, tenant_id=user.tenant_id)
    return user, access, refresh_raw


def refresh(
    db: Session,
    *,
    refresh_token: str,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[User, str, str]:
    """Rotate a refresh token, revoking the whole family if an already-rotated one comes back."""
    s = get_settings()
    row = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(refresh_token))
        # Two concurrent refreshes would otherwise both pass every check and both issue.
        .with_for_update()
    )
    if row is None or row.expires_at <= _now():
        raise Unauthorized(_BAD_REFRESH)

    if row.revoked_at is not None:
        _handle_reuse(db, row, grace=s.refresh_reuse_grace_seconds)
        raise Unauthorized(_BAD_REFRESH)

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        # Read every time, so deactivating an account takes effect within one access-token life.
        raise Unauthorized(_BAD_REFRESH)

    access, raw, new_row = _issue(db, user, family_id=row.family_id, user_agent=user_agent, ip=ip)
    db.flush()
    row.revoked_at = _now()
    row.replaced_by_id = new_row.id
    db.commit()
    return user, access, raw


def _handle_reuse(db: Session, row: RefreshToken, *, grace: int) -> None:
    """Decide whether a rotated token coming back is theft or merely a race.

    Two requests sharing a session will present the same token at the same moment, and the
    loser is not an attacker. Inside the grace window it is simply rejected. Outside it, the
    token has been replayed long after its replacement was handed out, so the family dies.
    """
    replacement = db.get(RefreshToken, row.replaced_by_id) if row.replaced_by_id else None
    benign = (
        row.revoked_at is not None
        and row.revoked_at > _now() - timedelta(seconds=grace)
        and replacement is not None
        and replacement.revoked_at is None
    )
    if benign:
        log.info("auth.refresh_race", user_id=row.user_id, family_id=row.family_id)
        return

    log.warning("auth.refresh_reuse", user_id=row.user_id, family_id=row.family_id)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    db.commit()


def logout(db: Session, *, refresh_token: str, all_devices: bool = False) -> None:
    """Idempotent by design: an unknown or already-revoked token is not an error, and saying so
    would tell a caller whether a token was ever real."""
    row = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(refresh_token))
    )
    if row is None:
        return

    where = (RefreshToken.user_id == row.user_id) if all_devices else (RefreshToken.id == row.id)
    db.execute(
        update(RefreshToken)
        .where(where, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    db.commit()
    log.info("auth.logout", user_id=row.user_id, all_devices=all_devices)


def current_user(db: Session, tenant_id: str, user_id: str) -> User:
    """The user behind a valid token, or 404 when there is none.

    Not an edge case: every token the eval harness and the test fixtures mint names a subject
    with no row, and this must stay a clean 404 rather than a 500.
    """
    user = db.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        raise NotFound("user not found")
    return user


def purge_expired_refresh_tokens(db: Session) -> int:
    """Called at startup, alongside `reap_stale_runs`. Keeps revoked rows for a month so a
    reuse arriving late is still recognised as reuse rather than as an unknown token."""
    cutoff = _now() - timedelta(days=30)
    result = db.execute(RefreshToken.__table__.delete().where(RefreshToken.expires_at < cutoff))
    db.commit()
    return result.rowcount or 0

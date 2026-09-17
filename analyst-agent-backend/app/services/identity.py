"""Which account, and so which tenant, a verified Supabase identity belongs to.

Supabase proves who is calling. This module is the only place that turns that into an account
here: finding it, adopting an older account by its email, or creating an organisation for a
person signing in for the first time.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Tenant, User
from app.logging import log
from app.security.supabase import Identity
from app.services.errors import Conflict, Forbidden, NotFound, OnboardingRequired


def _now() -> datetime:
    return datetime.now(UTC)


def resolve(db: Session, identity: Identity) -> User:
    """The active account behind `identity`.

    Raises OnboardingRequired when there is none, and Forbidden when it is disabled.
    """
    user = db.execute(select(User).where(User.auth_user_id == identity.sub)).scalar_one_or_none()
    if user is None:
        user = _adopt(db, identity)
    if user is None:
        raise OnboardingRequired("this account has no organisation yet")
    if not user.is_active:
        raise Forbidden("this account has been disabled")
    return user


def _adopt(db: Session, identity: Identity) -> User | None:
    """Link an account from before Supabase to the identity that proves its email address.

    Only a verified address qualifies. Without that check, signing up with someone's email and
    never confirming it would be enough to walk into their organisation.
    """
    if not identity.email_verified:
        return None
    user = db.execute(
        select(User).where(User.email == identity.email, User.auth_user_id.is_(None))
    ).scalar_one_or_none()
    if user is None:
        return None

    user.auth_user_id = identity.sub
    user.last_login_at = _now()
    try:
        db.commit()
    except IntegrityError:
        # A concurrent first request from the same person linked it a moment ago.
        db.rollback()
        return db.execute(
            select(User).where(User.auth_user_id == identity.sub)
        ).scalar_one_or_none()
    log.info("identity.adopted", user_id=user.id, tenant_id=user.tenant_id)
    return user


def provision(db: Session, identity: Identity, tenant_name: str) -> User:
    """Create an organisation with `identity` as its owner."""
    if not get_settings().allow_open_signup:
        raise Forbidden("sign-up is closed")

    taken = db.execute(
        select(User.id).where((User.auth_user_id == identity.sub) | (User.email == identity.email))
    ).first()
    if taken is not None:
        raise Conflict("an account already exists for this email address")

    tenant = Tenant(name=tenant_name)
    user = User(
        tenant=tenant,
        auth_user_id=identity.sub,
        email=identity.email,
        name=identity.name,
        role="owner",
        last_login_at=_now(),
    )
    db.add_all([tenant, user])
    try:
        db.commit()
    except IntegrityError as e:
        # Two submissions of the same form raced past the check above.
        db.rollback()
        raise Conflict("an account already exists for this email address") from e
    db.refresh(user)
    log.info("identity.provisioned", user_id=user.id, tenant_id=user.tenant_id)
    return user


def current_user(db: Session, tenant_id: str, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None or user.tenant_id != tenant_id:
        raise NotFound("user not found")
    return user

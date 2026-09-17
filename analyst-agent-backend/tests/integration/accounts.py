"""Accounts for integration tests: an App DB user linked to a (fake) Supabase identity."""

import uuid

from sqlalchemy.orm import Session

from tests import supabase_tokens


def create_account(db: Session, tenant_id: str, email: str | None = None) -> str:
    """Give `tenant_id` a member signed in through Supabase, and return their access token.

    The tenant is created when it does not exist yet, so two accounts can share one.
    """
    from app.db.models import Tenant, User

    if db.get(Tenant, tenant_id) is None:
        db.add(Tenant(id=tenant_id, name=tenant_id))
    sub = str(uuid.uuid4())
    email = email or f"{tenant_id}-{sub[:8]}@example.com"
    db.add(User(tenant_id=tenant_id, email=email, auth_user_id=sub))
    db.commit()
    return supabase_tokens.mint(sub=sub, email=email)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}

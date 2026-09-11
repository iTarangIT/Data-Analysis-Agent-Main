import pytest
from sqlalchemy import text

DEMO_DSN = "postgresql+psycopg://analyst_ro:ro@localhost:5432/demo"


@pytest.fixture(scope="session")
def demo_dsn() -> str:
    return DEMO_DSN


@pytest.fixture
def clean_app_db():
    """Integration tests share one App DB, so each starts from a known state."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        # Order matters: refresh_tokens references users, and users references tenants.
        db.execute(text("DELETE FROM refresh_tokens"))
        db.execute(text("DELETE FROM users"))
        db.execute(text("DELETE FROM runs"))
        db.execute(text("DELETE FROM connections"))
        db.execute(text("DELETE FROM tenants"))
        db.commit()
        yield db
    finally:
        db.close()


@pytest.fixture
def other_token() -> str:
    from jose import jwt

    from app.config import get_settings

    return jwt.encode(
        {"tenant_id": "t_other", "sub": "u_other"},
        get_settings().jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


@pytest.fixture
def registered(client, clean_app_db):
    """A real signed-up account, as opposed to the hand-minted `token` fixture.

    Returns the register response body, so a test can reach the tokens, the user and the
    tenant it created.
    """

    def _register(email: str = "owner@example.com", password: str = "a-long-enough-password"):
        r = client.post(
            "/auth/register",
            json={"email": email, "password": password, "tenant_name": "Acme"},
        )
        assert r.status_code == 201, r.text
        return r.json()

    return _register


@pytest.fixture
def auth_headers(registered):
    body = registered()
    return {"Authorization": f"Bearer {body['access_token']}"}

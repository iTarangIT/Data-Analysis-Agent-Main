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

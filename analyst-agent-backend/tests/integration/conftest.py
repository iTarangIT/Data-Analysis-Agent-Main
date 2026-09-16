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
        # Order matters: refresh_tokens references users, users and connections reference
        # tenants, and connection_tables and runs reference connections.
        db.execute(text("DELETE FROM refresh_tokens"))
        db.execute(text("DELETE FROM users"))
        db.execute(text("DELETE FROM runs"))
        db.execute(text("DELETE FROM connection_tables"))
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


@pytest.fixture(autouse=True)
def mcp_in_process(monkeypatch):
    """Send MCP calls straight to the server's own tool functions instead of over HTTP.

    The MCP server is a separate process that reads its own settings, so under the suite it
    holds a different `CREDENTIAL_ENCRYPTION_KEY` than the one these tests encrypt with, and
    every connection would fail to open. Dispatching in-process runs the real tools, the real
    guard and the real catalog readers against the test's own settings.

    What this does not cover is the transport, so it is not the only thing covering it:
    `test_database_mcp.py` drives the tools through the server's own context, and `probe_mcp`
    checks the wire at boot.
    """
    from mcp.server.auth.provider import AccessToken
    from pydantic import BaseModel

    from app import database_mcp, mcp_client

    def as_wire(value):
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [as_wire(v) for v in value]
        return value

    tools = {
        "list_tables": database_mcp.list_tables,
        "read_tables": database_mcp.read_tables,
        "table_stats": database_mcp.table_stats,
        "run_select": database_mcp.run_select,
    }

    def call(tenant_id, connection_id, tool, args):
        monkeypatch.setattr(
            database_mcp,
            "get_access_token",
            lambda: AccessToken(
                token="test",
                client_id="analyst-agent",
                scopes=["database:read"],
                claims={"tenant_id": tenant_id, "connection_id": connection_id},
            ),
        )
        return as_wire(tools[tool](**args))

    monkeypatch.setattr(mcp_client, "call", call)

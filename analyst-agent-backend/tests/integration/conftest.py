import pytest
from sqlalchemy import text

from tests.integration.accounts import create_account

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
        # Order matters: users and connections reference tenants, and connection_tables and
        # runs reference connections.
        db.execute(text("DELETE FROM users"))
        db.execute(text("DELETE FROM runs"))
        db.execute(text("DELETE FROM connection_tables"))
        db.execute(text("DELETE FROM dataset_files"))
        db.execute(text("DELETE FROM dataset_sources"))
        db.execute(text("DELETE FROM connections"))
        db.execute(text("DELETE FROM tenants"))
        db.commit()
        yield db
    finally:
        db.close()


@pytest.fixture
def token(clean_app_db) -> str:
    """A member of `t_test`. Depends on `clean_app_db` so the wipe cannot run after it and
    delete the account the token names."""
    return create_account(clean_app_db, "t_test")


@pytest.fixture
def other_token(clean_app_db) -> str:
    return create_account(clean_app_db, "t_other")


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

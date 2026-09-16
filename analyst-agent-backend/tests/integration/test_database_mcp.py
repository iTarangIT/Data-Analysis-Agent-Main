"""What the MCP server refuses.

It is the only process that decrypts a customer DSN, so the checks it makes before opening one
are the tenant boundary. Nothing in a tool's arguments names a connection: the token does, and
these cover what happens when that token says something it should not.

The tools are called as plain functions with a stubbed access token, which is the same path a
real request takes once the token has been verified - `tests/unit/test_mcp_auth.py` covers the
verifying.
"""

import uuid

import pytest
from mcp.server.auth.provider import AccessToken

from app import database_mcp
from app.db.models import Connection, ConnectionTable
from app.security import vault

pytestmark = pytest.mark.integration


@pytest.fixture
def db():
    """A throwaway tenant of its own rather than `clean_app_db`, which empties the App DB - on a
    development machine that is somebody's real account and their connections."""
    from app.db.models import Tenant
    from app.db.session import SessionLocal

    session = SessionLocal()
    tenant = Tenant(id=f"t_mcp_{uuid.uuid4().hex[:8]}", name="mcp test")
    session.add(tenant)
    session.commit()
    try:
        yield session, tenant.id
    finally:
        session.rollback()
        ids = [c.id for c in session.query(Connection).filter(Connection.tenant_id == tenant.id)]
        if ids:
            session.query(ConnectionTable).filter(ConnectionTable.connection_id.in_(ids)).delete(
                synchronize_session=False
            )
            session.query(Connection).filter(Connection.tenant_id == tenant.id).delete(
                synchronize_session=False
            )
        session.delete(session.get(Tenant, tenant.id))
        session.commit()
        session.close()


@pytest.fixture
def connection(db, demo_dsn):
    session, tenant_id = db
    conn = Connection(
        tenant_id=tenant_id,
        name="demo",
        kind="postgres",
        secret_enc=vault.encrypt({"dsn": demo_dsn}),
    )
    session.add(conn)
    session.commit()
    session.refresh(conn)
    return conn


@pytest.fixture
def as_token(monkeypatch):
    def _act(tenant_id: str | None, connection_id: str | None):
        claims = {}
        if tenant_id is not None:
            claims["tenant_id"] = tenant_id
        if connection_id is not None:
            claims["connection_id"] = connection_id
        monkeypatch.setattr(
            database_mcp,
            "get_access_token",
            lambda: AccessToken(
                token="t", client_id="analyst-agent", scopes=["database:read"], claims=claims
            ),
        )

    return _act


def test_a_token_for_the_right_tenant_reads_the_database(connection, as_token):
    as_token(connection.tenant_id, connection.id)

    assert "telemetry" in database_mcp.list_tables()


def test_a_token_for_another_tenant_cannot_open_the_connection(connection, as_token):
    as_token("t_someone_else", connection.id)

    with pytest.raises(ValueError, match="connection not found"):
        database_mcp.list_tables()


def test_a_token_naming_no_connection_cannot_open_anything(connection, as_token):
    """This is the shape `probe_mcp`'s token has, so the boot check can never read a database."""
    as_token(connection.tenant_id, None)

    with pytest.raises(ValueError, match="database context is missing"):
        database_mcp.list_tables()


def test_a_deleted_connection_is_refused(connection, db, as_token):
    from datetime import UTC, datetime

    connection.deleted_at = datetime.now(UTC)
    db[0].commit()
    as_token(connection.tenant_id, connection.id)

    with pytest.raises(ValueError, match="connection not found"):
        database_mcp.list_tables()


def test_a_query_is_allowed_only_over_the_chosen_tables(connection, db, as_token):
    db[0].add(ConnectionTable(connection_id=connection.id, name="telemetry", selected=True))
    db[0].add(ConnectionTable(connection_id=connection.id, name="dealers", selected=False))
    db[0].commit()
    as_token(connection.tenant_id, connection.id)

    chosen = database_mcp.run_select("SELECT count(*) AS n FROM telemetry", 501)
    refused = database_mcp.run_select("SELECT * FROM dealers", 501)

    assert chosen.error is None and chosen.rows == [[240]]
    assert "dealers" in (refused.error or "")


def test_nothing_is_allowed_before_any_table_is_chosen(connection, as_token):
    """A connection whose tables nobody has chosen answers nothing, rather than everything."""
    as_token(connection.tenant_id, connection.id)

    result = database_mcp.run_select("SELECT count(*) FROM telemetry", 501)

    assert "telemetry" in (result.error or "")


def test_a_write_never_reaches_the_database_even_with_the_table_chosen(connection, db, as_token):
    db[0].add(ConnectionTable(connection_id=connection.id, name="dealers", selected=True))
    db[0].commit()
    as_token(connection.tenant_id, connection.id)

    result = database_mcp.run_select("DELETE FROM dealers", 501)

    assert result.rows == []
    assert "SELECT" in (result.error or "")

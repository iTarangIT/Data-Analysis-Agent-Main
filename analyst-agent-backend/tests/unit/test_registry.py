"""`connector_for` is where a connection's kind decides what the agent talks to, and - for the
kinds this process still owns - the only place a credential is decrypted."""

import pytest

from app.connectors.mcp import McpConnector
from app.connectors.registry import connector_for
from app.db.models import Connection
from app.security import vault


def _connection(kind: str, secret: dict) -> Connection:
    return Connection(
        id="c1", tenant_id="t_a", name="src", kind=kind, secret_enc=vault.encrypt(secret)
    )


def test_a_postgres_connection_is_reached_through_mcp():
    conn = _connection(
        "postgres", {"dsn": "postgresql+psycopg://analyst_ro:ro@localhost:5432/demo"}
    )

    connector = connector_for(conn)

    assert isinstance(connector, McpConnector)
    assert (connector.tenant_id, connector.connection_id) == ("t_a", "c1")


def test_building_a_postgres_connector_never_decrypts_the_credential(monkeypatch):
    """The DSN belongs to the MCP server now. If this process still reached for it, a leak here
    would put a customer's credential back in the public API's memory."""
    conn = _connection("postgres", {"dsn": "postgresql+psycopg://u:p@localhost:5432/x"})
    monkeypatch.setattr(
        vault, "decrypt", lambda _: pytest.fail("the API decrypted a Postgres credential")
    )

    connector_for(conn)


def test_an_unknown_kind_is_refused():
    conn = _connection("postgres", {"dsn": "postgresql+psycopg://u:p@localhost:5432/x"})
    conn.kind = "smoke-signals"

    with pytest.raises(ValueError, match="smoke-signals"):
        connector_for(conn)

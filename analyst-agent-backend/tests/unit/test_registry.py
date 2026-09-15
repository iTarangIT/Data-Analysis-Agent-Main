"""`connector_for` is the only place a credential is decrypted, and the only place a
connection's kind decides what the agent talks to."""

import pytest

from app.connectors.postgres import PostgresConnector
from app.connectors.registry import connector_for
from app.db.models import Connection
from app.security import vault


def _connection(kind: str, secret: dict) -> Connection:
    return Connection(
        id="c1", tenant_id="t_a", name="src", kind=kind, secret_enc=vault.encrypt(secret)
    )


def test_a_postgres_connection_builds_a_postgres_connector():
    conn = _connection(
        "postgres", {"dsn": "postgresql+psycopg://analyst_ro:ro@localhost:5432/demo"}
    )

    assert isinstance(connector_for(conn), PostgresConnector)


def test_an_unknown_kind_is_refused():
    conn = _connection("postgres", {"dsn": "postgresql+psycopg://u:p@localhost:5432/x"})
    conn.kind = "smoke-signals"

    with pytest.raises(ValueError, match="smoke-signals"):
        connector_for(conn)

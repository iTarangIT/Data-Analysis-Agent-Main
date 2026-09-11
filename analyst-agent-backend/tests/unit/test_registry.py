"""`connector_for` is the only place a credential is decrypted, and the only place a
connection's kind decides what the agent talks to."""

import pytest

from app.connectors.postgres import PostgresConnector
from app.connectors.registry import connector_for
from app.connectors.web import WebConnector
from app.db.models import Connection
from app.security import vault


def _connection(kind: str, secret: dict) -> Connection:
    return Connection(
        id="c1", tenant_id="t_a", name="src", kind=kind, secret_enc=vault.encrypt(secret)
    )


def test_a_web_connection_builds_a_web_connector():
    conn = _connection("web", {"url": "https://d.example", "username": "u", "password": "p"})

    connector = connector_for(conn)

    assert isinstance(connector, WebConnector)
    assert connector.kind == "web"


def test_the_web_connector_is_scoped_to_the_row_it_came_from():
    conn = _connection("web", {"url": "https://d.example", "username": "u", "password": "p"})

    connector = connector_for(conn)

    assert (connector.tenant_id, connector.connection_id) == ("t_a", "c1")


def test_a_postgres_connection_still_builds_a_postgres_connector():
    conn = _connection(
        "postgres", {"dsn": "postgresql+psycopg://analyst_ro:ro@localhost:5432/demo"}
    )

    assert isinstance(connector_for(conn), PostgresConnector)


def test_an_unknown_kind_is_refused():
    conn = _connection("postgres", {"dsn": "postgresql+psycopg://u:p@localhost:5432/x"})
    conn.kind = "smoke-signals"

    with pytest.raises(ValueError, match="smoke-signals"):
        connector_for(conn)

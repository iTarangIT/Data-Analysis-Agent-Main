"""Hard rule 4: customer data is read-only at three independent layers. This proves the two
that live outside the guard - the database role and the connector's connection options."""

import pytest
from sqlalchemy.exc import DatabaseError

pytestmark = pytest.mark.integration


@pytest.fixture
def connector(demo_dsn):
    from app.connectors.postgres import PostgresConnector

    return PostgresConnector(demo_dsn)


def test_the_connection_works_at_all(connector):
    assert connector.test() is True


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM dealers",
        "UPDATE dealers SET name = 'x'",
        "INSERT INTO dealers (name, city, created_at) VALUES ('x', 'y', '2026-01-01')",
        "CREATE TABLE sneaky (id int)",
        "DROP TABLE telemetry",
    ],
)
def test_every_write_is_refused_by_the_database_itself(connector, statement):
    # Deliberately bypasses the guard: if this ever passes, the role is misconfigured and the
    # guard is the only thing standing between a model and the customer's data.
    with pytest.raises(DatabaseError, match="read-only transaction"):
        connector.run_select(statement, max_rows=1)


def test_reads_still_work(connector):
    cols, rows = connector.run_select("SELECT count(*) AS n FROM telemetry", max_rows=1)
    assert cols == ["n"] and rows[0][0] == 240


def test_schema_introspection_finds_the_seeded_tables(connector):
    names = {t["name"] for t in connector.describe_schema()["tables"]}
    assert {"dealers", "batteries", "telemetry"} <= names


def test_partition_children_are_hidden_but_the_parent_is_shown(connector):
    """The real IoT schema is 115 tables of which 100 are weekly partitions. Listing children
    would swamp the generator's prompt and let the guard allow a query against one directly."""
    names = {t["name"] for t in connector.describe_schema()["tables"]}
    assert "readings" in names
    assert not {n for n in names if n.startswith("readings_p")}


def test_the_parent_partition_can_still_be_queried(connector):
    _, rows = connector.run_select("SELECT count(*) AS n FROM readings", max_rows=1)
    assert rows[0][0] == 3

"""Hard rule 4: customer data is read-only at three independent layers. This proves the two
that live outside the guard - the database role and the connection options - where they now
live, inside the MCP server, which is the only thing that opens a customer database.

Everything here goes straight at the engine rather than through `run_select`, because
`run_select` guards first and the point is to prove what holds when the guard does not."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.database_mcp import CustomerDatabase

pytestmark = pytest.mark.integration


@pytest.fixture
def database(demo_dsn):
    customer = CustomerDatabase(demo_dsn)
    yield customer
    customer.close()


def _scalar(database, statement):
    with database.engine.connect() as conn:
        return conn.execute(text(statement)).fetchone()


def test_the_connection_works_at_all(database):
    assert _scalar(database, "SELECT 1")[0] == 1


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
def test_every_write_is_refused_by_the_database_itself(database, statement):
    # If this ever passes, the role is misconfigured and the guard is the only thing standing
    # between a model and the customer's data.
    with pytest.raises(DatabaseError, match="read-only transaction"):
        _scalar(database, statement)


def test_reads_still_work(database):
    assert _scalar(database, "SELECT count(*) AS n FROM telemetry")[0] == 240


def test_a_bare_table_name_can_only_resolve_in_public(database):
    # The guard allows bare names by matching them against tables in `public`. A role whose
    # search_path put another schema first would make that match mean a different table.
    assert _scalar(database, "SHOW search_path")[0] == "public"


def test_the_parent_partition_can_still_be_queried(database):
    assert _scalar(database, "SELECT count(*) AS n FROM readings")[0] == 3


def test_the_guard_still_refuses_a_table_nobody_chose(database):
    """The third layer, in the one place it now runs: even reaching the server directly, a
    statement naming an unselected table never reaches the database."""
    result = database.run_select("SELECT * FROM dealers", 1, allowed={"telemetry"})

    assert result.rows == []
    assert "dealers" in (result.error or "")

"""The Postgres schema reader, against the real catalog of the `demo` fixture.

Only structure is read, so these hold for the fixture as seeded by any version of
`scripts/demo_customer.sql`; none of them depends on what the tables contain.
"""

import re

import pytest
from sqlalchemy import event

from app.catalog.types import Column, ForeignKey
from app.connectors.postgres import PostgresConnector

pytestmark = pytest.mark.integration

SEEDED = ["batteries", "dealers", "readings", "telemetry"]


@pytest.fixture(scope="module")
def connector(demo_dsn):
    return PostgresConnector(demo_dsn)


@pytest.fixture(scope="module")
def tables(connector):
    return {t.name: t for t in connector.read_tables(SEEDED)}


def test_it_lists_a_partitioned_parent_and_never_its_partitions(connector):
    """The real IoT schema is 115 tables of which 100 are weekly partitions. Listing children
    would swamp the picker and let a person select one week of a table instead of the table."""
    names = connector.list_tables()

    assert set(SEEDED) <= set(names)
    assert not [n for n in names if n.startswith("readings_p")]


def test_it_reads_only_real_tables_it_was_asked_for(connector):
    read = connector.read_tables(["dealers", "readings_p20260901", "no_such_table"])

    assert [t.name for t in read] == ["dealers"]


def test_columns_carry_postgres_own_type_names_and_nullability(tables):
    assert tables["telemetry"].columns[:3] == [
        Column(name="id", type="bigint", nullable=False),
        Column(name="battery_id", type="integer", nullable=True),
        # Not "TIMESTAMP": the time zone is the difference between a right and a wrong filter.
        Column(name="ts", type="timestamp with time zone", nullable=False),
    ]
    assert {c.name: c.type for c in tables["batteries"].columns}["price_inr"] == "numeric(12,2)"


def test_primary_keys(tables):
    assert tables["dealers"].primary_key == ["id"]
    assert tables["readings"].primary_key == []


def test_foreign_keys(tables):
    assert tables["batteries"].foreign_keys == [
        ForeignKey(columns=["dealer_id"], ref_table="dealers", ref_columns=["id"])
    ]
    assert tables["telemetry"].foreign_keys == [
        ForeignKey(columns=["battery_id"], ref_table="batteries", ref_columns=["id"])
    ]


def test_unique_constraints(tables):
    assert tables["batteries"].uniques == [["imei"]]
    assert tables["dealers"].uniques == []


def test_reading_structure_never_selects_from_a_customer_table(connector):
    issued: list[str] = []

    def capture(conn, cursor, statement, *args):
        issued.append(statement)

    event.listen(connector.engine, "before_cursor_execute", capture)
    try:
        connector.read_tables(SEEDED)
    finally:
        event.remove(connector.engine, "before_cursor_execute", capture)

    reads_a_table = re.compile(rf'\b(FROM|JOIN)\s+(public\.)?"?({"|".join(SEEDED)})\b', re.I)
    assert issued, "nothing was captured, so this proves nothing"
    assert [s for s in issued if reads_a_table.search(s)] == []

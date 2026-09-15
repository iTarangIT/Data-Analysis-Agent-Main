"""What `describe_schema` reports about the demo database, against the real catalog.

These need the fixture from `scripts/demo_customer.sql` as it stands after the missing-data
work, which added an empty `trips` and a `gps_pings` whose data stops on 2026-07-02 with a
partition already created ahead of it. Reseed before running them.
"""

import pytest

from app.connectors.postgres import SCHEMA_VERSION, PostgresConnector

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def schema(demo_dsn):
    return PostgresConnector(demo_dsn).describe_schema(sample_rows=0)


def _stats(schema, name):
    return next(t["stats"] for t in schema["tables"] if t["name"] == name)


def test_the_cache_is_stamped_so_an_older_one_is_refreshed(schema):
    assert schema["v"] == SCHEMA_VERSION


def test_an_empty_table_is_reported_as_empty(schema):
    assert _stats(schema, "trips") == {"rows": "empty"}


def test_a_populated_table_is_never_reported_as_empty(schema):
    for name in ("dealers", "batteries", "telemetry", "readings", "gps_pings"):
        assert _stats(schema, name)["rows"] != "empty", name


def test_coverage_skips_the_partition_created_ahead_of_the_data(schema):
    """The defect worth a test of its own.

    `gps_pings_p20260706` exists and is empty. Reading the newest bound rather than the newest
    bound that holds rows would tell the model the data runs to 2026-07-13, a week past the
    last row, and the model would repeat that as fact.
    """
    assert _stats(schema, "gps_pings")["covered_to"] == "2026-07-06"


def test_an_unpartitioned_table_claims_no_coverage_date(schema):
    # It could only come from max(ts), which is a full scan on the tables this matters for.
    assert "covered_to" not in _stats(schema, "dealers")


def test_the_row_counts_survive_the_fixture_being_analysed(schema):
    # demo_customer.sql runs ANALYZE, so these are real estimates rather than "nonempty".
    assert _stats(schema, "telemetry")["rows"] == "few"


def test_partition_children_never_appear_as_tables(schema):
    names = {t["name"] for t in schema["tables"]}

    assert "gps_pings" in names
    assert not [n for n in names if n.startswith("gps_pings_p")]

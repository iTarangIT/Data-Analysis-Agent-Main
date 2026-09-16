"""What the connector reports each demo table holds, against the real catalog.

These need the fixture from `scripts/demo_customer.sql` as it stands after the missing-data
work, which added an empty `trips` and a `gps_pings` whose data stops on 2026-07-02 with a
partition already created ahead of it. Reseed before running them.
"""

import pytest

from app.database_mcp import CustomerDatabase

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def stats(demo_dsn):
    connector = CustomerDatabase(demo_dsn)
    return connector.table_stats(connector.list_tables())


def test_an_empty_table_is_reported_as_empty(stats):
    assert stats["trips"] == {"rows": "empty"}


def test_a_populated_table_is_never_reported_as_empty(stats):
    for name in ("dealers", "batteries", "telemetry", "readings", "gps_pings"):
        assert stats[name]["rows"] != "empty", name


def test_coverage_skips_the_partition_created_ahead_of_the_data(stats):
    """The defect worth a test of its own.

    `gps_pings_p20260706` exists and is empty. Reading the newest bound rather than the newest
    bound that holds rows would tell the model the data runs to 2026-07-13, a week past the
    last row, and the model would repeat that as fact.
    """
    assert stats["gps_pings"]["covered_to"] == "2026-07-06"


def test_an_unpartitioned_table_claims_no_coverage_date(stats):
    # It could only come from max(ts), which is a full scan on the tables this matters for.
    assert "covered_to" not in stats["dealers"]


def test_the_row_counts_survive_the_fixture_being_analysed(stats):
    # demo_customer.sql runs ANALYZE, so these are real estimates rather than "nonempty".
    assert stats["telemetry"]["rows"] == "few"

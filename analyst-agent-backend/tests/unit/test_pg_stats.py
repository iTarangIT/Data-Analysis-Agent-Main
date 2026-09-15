"""Reading a partition bound and sizing a table, without a database.

Every rule here is about refusing to state something the catalog does not actually prove.
The live queries are covered by tests/integration/test_schema_stats.py.
"""

import pytest

from app.connectors.pg_stats import _bucket, _coverage, _magnitude, _upper_bound


class Child:
    def __init__(self, name, approx_rows, bound):
        self.child = name
        self.approx_rows = approx_rows
        self.bound = bound


class TestUpperBound:
    def test_it_reads_a_range_bound(self):
        bound = "FOR VALUES FROM ('2026-06-29 00:00:00+00') TO ('2026-07-06 00:00:00+00')"

        assert _upper_bound(bound) == "2026-07-06"

    def test_a_bound_that_is_not_midnight_keeps_its_time(self):
        bound = "FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-09-07 18:30:00+00')"

        assert _upper_bound(bound) == "2026-09-07 18:30:00+00"

    @pytest.mark.parametrize(
        "bound",
        [
            None,
            "DEFAULT",
            "FOR VALUES IN ('north', 'south')",
            "FOR VALUES WITH (modulus 4, remainder 0)",
            "FOR VALUES FROM ('2026-01-01') TO (MAXVALUE)",
            "FOR VALUES FROM ('2026-01-01', 'a') TO ('2026-02-01', 'b')",
        ],
    )
    def test_anything_it_cannot_read_exactly_is_refused(self, bound):
        # A guessed coverage date is worse than none: the model would quote it as a fact.
        assert _upper_bound(bound) is None


class TestCoverage:
    def test_it_skips_partitions_created_ahead_of_the_data(self):
        """The defect this whole module exists to avoid.

        Partitions are routinely created weeks before anything is written to them, so the
        newest bound describes the schedule rather than the data. A pipeline that stopped in
        early July would otherwise advertise coverage into the following week.
        """
        children = [
            Child(
                "p0629",
                4,
                "FOR VALUES FROM ('2026-06-29 00:00:00+00') TO ('2026-07-06 00:00:00+00')",
            ),
            Child(
                "p0706",
                0,
                "FOR VALUES FROM ('2026-07-06 00:00:00+00') TO ('2026-07-13 00:00:00+00')",
            ),
        ]

        assert _coverage(None, "gps_pings", children) == "2026-07-06"

    def test_a_default_partition_makes_the_claim_unsafe(self):
        # Rows outside every range land in the default one, so the highest bound stops
        # describing where the data ends.
        children = [
            Child(
                "p0629",
                4,
                "FOR VALUES FROM ('2026-06-29 00:00:00+00') TO ('2026-07-06 00:00:00+00')",
            ),
            Child("pdef", 9, "DEFAULT"),
        ]

        assert _coverage(None, "gps_pings", children) is None

    def test_no_readable_bounds_reports_nothing(self):
        assert _coverage(None, "t", [Child("p", 1, "FOR VALUES IN ('x')")]) is None


class TestSizing:
    @pytest.mark.parametrize(
        ("rows", "expected"),
        [
            (1, "few"),
            (999, "few"),
            (1_000, "thousands"),
            (999_999, "thousands"),
            (1_000_000, "millions"),
            (45_900_000, "millions"),
        ],
    )
    def test_buckets(self, rows, expected):
        assert _bucket(rows) == expected

    @pytest.mark.parametrize(
        ("rows", "expected"),
        [(45_899_998, 46_000_000), (33_142, 33_000), (240, 240), (7, 7)],
    )
    def test_it_rounds_to_two_significant_figures(self, rows, expected):
        # reltuples is a float4 and its last digits are noise. An exact-looking count would be
        # repeated by the model as a counted one, and would also move the tool description
        # under the eval cassettes every time autovacuum ran.
        assert _magnitude(rows) == expected

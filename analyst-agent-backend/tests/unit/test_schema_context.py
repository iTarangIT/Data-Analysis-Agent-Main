"""What the model is told about the selected tables before it writes a query.

This text is the model's whole knowledge of the database. It must never claim a key the catalog
does not hold, hide one that it does, or blur a guessed join into a declared one.
"""

from app.agent.schema_context import render_relationships, render_tables
from app.catalog.types import Catalog, CatalogTable, Column, Relationship, TableDef


def _catalog(*tables, relationships=()):
    return Catalog(tables=list(tables), relationships=list(relationships))


def _held(definition, stats=None):
    return CatalogTable(definition=definition, stats=stats)


class TestTables:
    def test_columns_carry_their_type_and_constraints(self):
        batteries = TableDef(
            name="batteries",
            columns=[
                Column(name="id", type="integer", nullable=False),
                Column(name="imei", type="text", nullable=False),
                Column(name="soc", type="numeric(5,2)"),
            ],
            primary_key=["id"],
            uniques=[["imei"]],
            checks=["soc >= 0"],
        )

        assert render_tables(_catalog(_held(batteries))) == (
            "TABLE batteries\n"
            "  id integer PRIMARY KEY\n"
            "  imei text NOT NULL UNIQUE\n"
            "  soc numeric(5,2)\n"
            "  CHECK (soc >= 0)"
        )

    def test_a_key_over_several_columns_is_stated_once_for_the_table(self):
        days = TableDef(
            name="days",
            columns=[
                Column(name="device", type="text", nullable=False),
                Column(name="day", type="date", nullable=False),
            ],
            primary_key=["day", "device"],
            uniques=[["device", "day"]],
        )

        assert render_tables(_catalog(_held(days))) == (
            "TABLE days\n"
            "  device text NOT NULL\n"
            "  day date NOT NULL\n"
            "  PRIMARY KEY (day, device)\n"
            "  UNIQUE (device, day)"
        )

    def test_comments_are_carried(self):
        vehicles = TableDef(
            name="vehicles",
            comment="One row per registered vehicle",
            columns=[Column(name="owner", type="text", comment="Registered owner")],
        )

        assert render_tables(_catalog(_held(vehicles))) == (
            "TABLE vehicles\n  -- One row per registered vehicle\n  owner text  -- Registered owner"
        )

    def test_tables_are_separated_so_each_reads_on_its_own(self):
        a = TableDef(name="alerts", columns=[Column(name="id", type="integer")])
        b = TableDef(name="vehicles", columns=[Column(name="id", type="integer")])

        assert render_tables(_catalog(_held(a), _held(b))) == (
            "TABLE alerts\n  id integer\n\nTABLE vehicles\n  id integer"
        )


class TestWhatATableHolds:
    """Without this the model cannot tell an empty table from a filter that matched nothing, and
    answers both with a shrug. The wording has to be exact about emptiness and vague about size.
    """

    def _header(self, stats):
        trips = TableDef(name="trips", columns=[Column(name="id", type="bigint")])
        return render_tables(_catalog(_held(trips, stats))).splitlines()[0]

    def test_an_empty_table_says_so_in_words_the_model_cannot_miss(self):
        assert self._header({"rows": "empty"}) == "TABLE trips  -- EMPTY, holds no rows at all"

    def test_a_table_proven_to_hold_rows_is_not_called_empty(self):
        # `reltuples` is -1 until a table is analysed, and 0 for one analysed while empty and
        # bulk-loaded since. Neither proves emptiness, so neither may be rendered as it.
        header = self._header({"rows": "nonempty"})

        assert "EMPTY" not in header
        assert "has rows" in header

    def test_a_size_is_a_bucket_rather_than_a_count(self):
        header = self._header({"rows": "millions", "rows_approx": 46_000_000})

        assert header == "TABLE trips  -- about 46,000,000 rows"

    def test_a_partial_estimate_says_it_is_a_floor(self):
        header = self._header(
            {"rows": "millions", "rows_approx": 46_000_000, "rows_at_least": True}
        )

        assert "at least about 46,000,000 rows" in header

    def test_stale_data_is_reported_as_where_the_rows_sit(self):
        # Not "data up to X": a partition bound is the edge of the partition, not the newest
        # row, and the description should not claim more than was measured.
        header = self._header({"rows": "millions", "covered_to": "2026-07-06"})

        assert "newest data sits in a partition ending 2026-07-06" in header

    def test_a_table_whose_statistics_could_not_be_read_still_renders(self):
        assert self._header(None) == "TABLE trips"


class TestRelationships:
    def test_a_declared_key_reads_as_a_join_with_its_direction(self):
        declared = Relationship(
            from_table="batteries",
            from_columns=["dealer_id"],
            to_table="dealers",
            to_columns=["id"],
            origin="declared",
            cardinality="many_to_one",
        )

        assert render_relationships(_catalog(relationships=[declared])) == (
            "  batteries.dealer_id -> dealers.id  (many-to-one)"
        )

    def test_an_inferred_join_says_it_is_only_a_name_match(self):
        inferred = Relationship(
            from_table="telemetry_gps",
            from_columns=["vehicleno"],
            to_table="vehicles",
            to_columns=["vehicleno"],
            origin="inferred",
            cardinality="many_to_one",
        )

        assert render_relationships(_catalog(relationships=[inferred])) == (
            "  telemetry_gps.vehicleno -> vehicles.vehicleno"
            "  (many-to-one, inferred from matching column names)"
        )

    def test_a_join_over_several_columns_pairs_them_in_order(self):
        composite = Relationship(
            from_table="readings",
            from_columns=["device", "day"],
            to_table="days",
            to_columns=["device", "day"],
            origin="declared",
            cardinality="one_to_one",
        )

        assert render_relationships(_catalog(relationships=[composite])) == (
            "  readings.(device, day) -> days.(device, day)  (one-to-one)"
        )

    def test_no_relationships_says_so_rather_than_leaving_a_blank(self):
        rendered = render_relationships(_catalog())

        assert rendered.strip()
        assert "->" not in rendered

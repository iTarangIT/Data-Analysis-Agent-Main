"""How the selected tables join, worked out from their keys alone.

The model writes joins from this map, and the guard rejects any table outside the selection, so
an edge to an unselected table or a guessed join between unrelated tables is not a harmless
extra: it costs the run a rejected query or a wrong answer.
"""

from app.catalog.relationships import map_relationships
from app.catalog.types import Column, ForeignKey, TableDef


def _table(name, columns, pk=(), uniques=(), fks=(), not_null=()):
    return TableDef(
        name=name,
        columns=[
            Column(name=c, type=t, nullable=c not in not_null and c not in pk)
            for c, t in columns.items()
        ],
        primary_key=list(pk),
        uniques=[list(u) for u in uniques],
        foreign_keys=list(fks),
    )


def _edges(tables):
    return [
        (r.from_table, r.from_columns, r.to_table, r.to_columns, r.origin, r.cardinality)
        for r in map_relationships(tables)
    ]


DEALERS = _table("dealers", {"id": "integer", "city": "text"}, pk=["id"])


class TestDeclared:
    def test_a_foreign_key_is_a_many_to_one_edge(self):
        batteries = _table(
            "batteries",
            {"id": "integer", "dealer_id": "integer"},
            pk=["id"],
            fks=[ForeignKey(columns=["dealer_id"], ref_table="dealers", ref_columns=["id"])],
        )

        assert _edges([DEALERS, batteries]) == [
            ("batteries", ["dealer_id"], "dealers", ["id"], "declared", "many_to_one")
        ]

    def test_a_composite_key_keeps_its_column_order(self):
        readings = _table(
            "readings",
            {"device": "text", "day": "date", "value": "integer"},
            fks=[
                ForeignKey(
                    columns=["device", "day"], ref_table="days", ref_columns=["device", "day"]
                )
            ],
        )
        days = _table("days", {"device": "text", "day": "date"}, pk=["day", "device"])

        assert _edges([readings, days]) == [
            ("readings", ["device", "day"], "days", ["device", "day"], "declared", "many_to_one")
        ]

    def test_a_key_that_is_also_the_tables_own_key_is_one_to_one(self):
        # Set equality, not order: a PK declared (b, a) still makes an FK on (a, b) one-to-one.
        profiles = _table(
            "profiles",
            {"dealer_id": "integer", "bio": "text"},
            pk=["dealer_id"],
            fks=[ForeignKey(columns=["dealer_id"], ref_table="dealers", ref_columns=["id"])],
        )

        assert _edges([DEALERS, profiles])[0][-1] == "one_to_one"

    def test_a_key_pointing_outside_the_selection_is_left_out(self):
        batteries = _table(
            "batteries",
            {"id": "integer", "dealer_id": "integer"},
            pk=["id"],
            fks=[ForeignKey(columns=["dealer_id"], ref_table="dealers", ref_columns=["id"])],
        )

        assert _edges([batteries]) == []


class TestInferredFromAKeyColumn:
    def test_a_column_matching_another_tables_primary_key(self):
        vehicles = _table("vehicles", {"vehicleno": "text", "owner": "text"}, pk=["vehicleno"])
        gps = _table("telemetry_gps", {"vehicleno": "character varying(20)", "lat": "real"})

        assert _edges([vehicles, gps]) == [
            ("telemetry_gps", ["vehicleno"], "vehicles", ["vehicleno"], "inferred", "many_to_one")
        ]

    def test_a_unique_not_null_column_counts_as_a_key(self):
        batteries = _table(
            "batteries",
            {"id": "integer", "imei": "text"},
            pk=["id"],
            uniques=[["imei"]],
            not_null=["imei"],
        )
        pings = _table("pings", {"imei": "text", "at": "timestamp with time zone"})

        assert _edges([batteries, pings]) == [
            ("pings", ["imei"], "batteries", ["imei"], "inferred", "many_to_one")
        ]

    def test_a_nullable_unique_column_does_not(self):
        batteries = _table(
            "batteries", {"id": "integer", "imei": "text"}, pk=["id"], uniques=[["imei"]]
        )
        pings = _table("pings", {"imei": "text"})

        assert _edges([batteries, pings]) == []

    def test_id_is_never_matched_by_name(self):
        # Every table has one, so a match on `id` would join everything to everything.
        alerts = _table("alerts", {"id": "integer"}, pk=["id"])

        assert _edges([DEALERS, alerts]) == []

    def test_two_tables_keyed_on_the_same_name_are_not_joined(self):
        # `countries.code` and `currencies.code` are both keys and unrelated.
        countries = _table("countries", {"code": "text"}, pk=["code"])
        currencies = _table("currencies", {"code": "text"}, pk=["code"])

        assert _edges([countries, currencies]) == []

    def test_types_from_different_families_do_not_match(self):
        vehicles = _table("vehicles", {"vehicleno": "text"}, pk=["vehicleno"])
        gps = _table("telemetry_gps", {"vehicleno": "bigint"})

        assert _edges([vehicles, gps]) == []

    def test_times_and_measurements_are_never_join_keys(self):
        days = _table("days", {"day": "date"}, pk=["day"])
        readings = _table("readings", {"day": "date", "value": "double precision"})
        scores = _table("scores", {"value": "double precision"}, pk=["value"])

        assert _edges([days, readings, scores]) == []


class TestInferredFromAnIdSuffix:
    def test_a_singular_prefix_finds_the_plural_table(self):
        trips = _table("trips", {"id": "bigint", "battery_id": "integer"}, pk=["id"])
        batteries = _table("batteries", {"id": "integer"}, pk=["id"])
        boxes = _table("boxes", {"id": "integer"}, pk=["id"])
        loads = _table("loads", {"id": "integer", "box_id": "integer"}, pk=["id"])

        assert _edges([trips, batteries, boxes, loads]) == [
            ("loads", ["box_id"], "boxes", ["id"], "inferred", "many_to_one"),
            ("trips", ["battery_id"], "batteries", ["id"], "inferred", "many_to_one"),
        ]

    def test_a_table_named_exactly_like_the_prefix(self):
        orders = _table("orders", {"id": "integer", "staff_id": "integer"}, pk=["id"])
        staff = _table("staff", {"id": "integer"}, pk=["id"])

        assert _edges([orders, staff]) == [
            ("orders", ["staff_id"], "staff", ["id"], "inferred", "many_to_one")
        ]

    def test_a_target_without_an_id_key_is_not_guessed_at(self):
        trips = _table("trips", {"id": "integer", "dealer_id": "integer"}, pk=["id"])
        dealers = _table("dealers", {"code": "text"}, pk=["code"])

        assert _edges([trips, dealers]) == []


class TestTheMapAsAWhole:
    def test_two_unique_columns_matching_each_other_are_one_relationship(self):
        # Each `imei` is a key the other table could point at, so the match is found from both
        # ends. Reported twice, the model would be told of two joins where there is one.
        batteries = _table(
            "batteries",
            {"id": "integer", "imei": "text"},
            pk=["id"],
            uniques=[["imei"]],
            not_null=["imei"],
        )
        modems = _table(
            "modems",
            {"id": "integer", "imei": "text"},
            pk=["id"],
            uniques=[["imei"]],
            not_null=["imei"],
        )

        assert _edges([modems, batteries]) == [
            ("batteries", ["imei"], "modems", ["imei"], "inferred", "one_to_one")
        ]

    def test_a_declared_key_suppresses_guesses_between_the_same_two_tables(self):
        batteries = _table(
            "batteries",
            {"id": "integer", "dealer_id": "integer", "city": "text"},
            pk=["id"],
            fks=[ForeignKey(columns=["dealer_id"], ref_table="dealers", ref_columns=["id"])],
        )
        dealers = _table(
            "dealers",
            {"id": "integer", "city": "text"},
            pk=["id"],
            uniques=[["city"]],
            not_null=["city"],
        )

        assert _edges([dealers, batteries]) == [
            ("batteries", ["dealer_id"], "dealers", ["id"], "declared", "many_to_one")
        ]

    def test_the_order_does_not_depend_on_the_order_tables_arrive_in(self):
        # The edges are rendered into the tool description, which the eval cassettes
        # fingerprint, so the same schema must always produce the same bytes.
        trips = _table("trips", {"id": "bigint", "battery_id": "integer"}, pk=["id"])
        batteries = _table("batteries", {"id": "integer"}, pk=["id"])
        loads = _table("loads", {"id": "integer", "battery_id": "integer"}, pk=["id"])

        assert _edges([trips, batteries, loads]) == _edges([loads, batteries, trips])

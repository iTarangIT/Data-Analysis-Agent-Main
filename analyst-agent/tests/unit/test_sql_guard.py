from typing import ClassVar

import pytest

from app.agent.nodes.sql_guard import sql_guard_node, validate_sql

ALLOWED = {"dealers", "batteries", "telemetry"}


def _ok(sql: str, max_rows: int = 100) -> str:
    safe, err = validate_sql(sql, ALLOWED, max_rows)
    assert err is None, f"unexpectedly rejected: {err}"
    return safe


def _rejected(sql: str, max_rows: int = 100) -> str:
    original, err = validate_sql(sql, ALLOWED, max_rows)
    assert err is not None, f"unexpectedly accepted: {original}"
    return err


class TestRowCap:
    def test_injects_limit_when_absent(self):
        assert "LIMIT 100" in _ok("select name from dealers")

    def test_caps_a_limit_above_the_maximum(self):
        assert "LIMIT 100" in _ok("select name from dealers limit 9999")

    def test_preserves_a_limit_below_the_maximum(self):
        safe = _ok("select name from dealers limit 5")
        assert "LIMIT 5" in safe and "LIMIT 100" not in safe

    def test_caps_a_set_operation(self):
        safe = _ok("select name from dealers union select city from dealers")
        assert "LIMIT 100" in safe and "UNION" in safe.upper()


class TestTableAllowlist:
    def test_rejects_a_table_outside_the_schema(self):
        assert "secrets" in _rejected("select * from secrets")

    def test_matching_is_case_insensitive(self):
        _ok("SELECT NAME FROM DEALERS")

    def test_accepts_a_schema_qualified_allowed_table(self):
        _ok("select name from public.dealers")

    def test_accepts_a_join_across_allowed_tables(self):
        _ok("select d.name from dealers d join batteries b on b.dealer_id = d.id")

    def test_cte_alias_is_not_mistaken_for_a_table(self):
        # The alias `recent` exists only inside the query. Treating it as a real table would
        # reject every CTE the SQL generator writes.
        _ok("with recent as (select * from telemetry) select battery_id from recent")

    def test_subquery_alias_is_not_mistaken_for_a_table(self):
        _ok("select t.id from (select id from dealers) t")


class TestForbiddenOperations:
    @pytest.mark.parametrize(
        "sql",
        [
            "delete from dealers",
            "update dealers set name = 'x'",
            "insert into dealers (name) values ('x')",
            "drop table dealers",
            "alter table dealers add column x int",
            "create table x (id int)",
            "truncate dealers",
            "grant select on dealers to public",
            "copy dealers to '/tmp/x.csv'",
            "set default_transaction_read_only = off",
        ],
    )
    def test_rejects_non_select_statements(self, sql):
        _rejected(sql)

    def test_rejects_dml_hidden_in_a_cte(self):
        _rejected("with x as (delete from dealers returning *) select * from x")

    def test_rejects_select_into_because_it_writes_a_table(self):
        # Parses as a plain Select, so only an explicit Into check catches it.
        _rejected("select * into newtbl from dealers")

    def test_rejects_more_than_one_statement(self):
        assert "one statement" in _rejected("select 1; delete from dealers")

    def test_rejects_unparseable_sql(self):
        assert "parse" in _rejected("select from where").lower()

    def test_rejects_empty_input(self):
        _rejected("")


class TestReturnContract:
    def test_returns_the_original_sql_when_rejected(self):
        original, err = validate_sql("delete from dealers", ALLOWED, 100)
        assert original == "delete from dealers" and err is not None

    def test_accepted_sql_round_trips_through_the_parser(self):
        safe = _ok("select count(*) from dealers")
        assert safe.upper().startswith("SELECT")


class TestNonLiteralRowCap:
    def test_caps_a_limit_that_is_not_a_plain_number(self):
        # A subquery limit cannot be compared against max_rows, so the cap is applied anyway.
        safe = _ok("select name from dealers limit (select 1)")
        assert "LIMIT 100" in safe

    def test_limit_all_is_treated_as_uncapped(self):
        assert "LIMIT 100" in _ok("select name from dealers limit all")


class TestGuardNode:
    SCHEMA: ClassVar[dict] = {"tables": [{"name": "dealers"}, {"name": "batteries"}]}

    def test_accepted_sql_is_written_back_and_clears_the_error(self):
        out = sql_guard_node({"sql": "select name from dealers", "schema": self.SCHEMA})
        assert out["guard_error"] is None and "LIMIT" in out["sql"]

    def test_rejection_records_the_reason_and_counts_a_retry(self):
        out = sql_guard_node({"sql": "delete from dealers", "schema": self.SCHEMA, "retries": 1})
        assert out["retries"] == 2 and "DELETE" in out["guard_error"]
        assert "sql" not in out

    def test_dml_buried_in_a_cte_is_named_as_a_forbidden_operation(self):
        out = sql_guard_node(
            {
                "sql": "with x as (delete from dealers returning *) select * from x",
                "schema": self.SCHEMA,
            }
        )
        assert "forbidden operation: Delete" in out["guard_error"]

    def test_first_rejection_starts_the_retry_count(self):
        out = sql_guard_node({"sql": "select * from secrets", "schema": self.SCHEMA})
        assert out["retries"] == 1

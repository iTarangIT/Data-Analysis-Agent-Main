import pytest

from app.agent.nodes.sql_guard import validate_sql

ALLOWED = {"dealers", "batteries", "telemetry"}
FILES = {"sales"}


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


class TestDuckDBDialect:
    """The file tool parses duckdb. Every rule must still hold, and the parse must round-trip
    duckdb syntax rather than quietly rewriting it into something duckdb rejects."""

    @pytest.mark.parametrize(
        "sql",
        [
            "select * from read_csv_auto('C:/Windows/win.ini')",
            "select * from read_csv('C:/x.csv')",
            "select * from read_parquet('C:/x.parquet')",
            "select * from read_json('C:/x.json')",
            "select * from glob('C:/*')",
            "select * from read_csv_auto('C:/x.csv') as sales",
            "select * from sales, read_csv('C:/x.csv')",
            "select * from (select * from read_csv('C:/x.csv')) t",
            "select * from 'C:/secret.parquet'",
        ],
    )
    def test_a_table_function_cannot_reach_the_filesystem(self, sql):
        _, err = validate_sql(sql, FILES, 500, "duckdb")

        assert err is not None

    def test_the_rejection_names_the_function_so_the_model_can_correct_it(self):
        _, err = validate_sql(
            "select * from read_csv_auto('C:/Windows/win.ini')", FILES, 500, "duckdb"
        )

        # "tables not allowed: ['']" told the model nothing, so it reissued the same query
        # until the tool budget ran out.
        assert "read_csv_auto" in err.lower()

    @pytest.mark.parametrize(
        "sql",
        [
            "copy sales to 'x.csv'",
            "copy (select * from sales) to 'x.parquet' (format parquet)",
            "attach 'other.db' as o",
            "install httpfs",
            "load httpfs",
            "pragma database_list",
            "set enable_external_access=true",
            "create table t as select * from sales",
            "delete from sales",
        ],
    )
    def test_only_selects_survive(self, sql):
        _, err = validate_sql(sql, FILES, 500, "duckdb")

        assert err is not None

    def test_an_allowed_file_table_is_accepted_and_capped(self):
        safe, err = validate_sql("select * from sales", FILES, 10, "duckdb")

        assert err is None
        assert "LIMIT 10" in safe.upper()

    def test_duckdb_syntax_is_not_rewritten_into_something_duckdb_rejects(self):
        """Parsing duckdb as postgres turns EXCLUDE into EXCEPT, which duckdb refuses. This is
        the concrete reason the dialect is threaded through rather than hardcoded."""
        safe, err = validate_sql("select * exclude (secret) from sales", FILES, 500, "duckdb")

        assert err is None
        assert "EXCLUDE" in safe.upper()

    def test_a_cte_still_resolves_locally(self):
        safe, err = validate_sql(
            "with recent as (select * from sales) select * from recent", FILES, 500, "duckdb"
        )

        assert err is None
        assert safe

    def test_postgres_remains_the_default(self):
        _, err = validate_sql("select * from sales", FILES, 500)

        assert err is None


class TestSchemaQualifiedNames:
    """A person chooses which tables the agent may use, so a qualifier must not reach around
    that choice to a same-named table somewhere else."""

    def test_an_allowed_name_in_another_schema_is_rejected(self):
        assert "other.dealers" in _rejected("select name from other.dealers")

    def test_a_catalog_qualified_table_is_rejected(self):
        _rejected("select name from demo.public.dealers")

    def test_system_catalogs_are_rejected_by_schema_rather_than_by_luck(self):
        # `information_schema.tables` used to pass only because no customer table is named
        # `tables`. One that is would have opened the whole catalog.
        _, err = validate_sql("select table_name from information_schema.tables", {"tables"}, 100)

        assert err is not None

    @pytest.mark.parametrize(
        "sql", ["select name from PUBLIC.dealers", 'select name from "public".dealers']
    )
    def test_public_is_accepted_however_it_is_written(self, sql):
        _ok(sql)

    def test_a_quoted_schema_keeps_its_case(self):
        # Postgres folds unquoted names only, so "Public" is a different schema from public.
        _rejected('select name from "Public".dealers')

    def test_duckdb_accepts_its_main_schema_and_nothing_else(self):
        assert validate_sql("select * from main.sales", FILES, 500, "duckdb")[1] is None
        assert validate_sql("select * from other.sales", FILES, 500, "duckdb")[1] is not None


class TestFunctionsThatReadTablesByName:
    """These take a table name or a query as a string, so the allowlist never sees the table
    they read. Used in FROM they already fail as unnamed tables; in an expression they did not.
    """

    @pytest.mark.parametrize(
        "sql",
        [
            "select query_to_xml('select * from secrets', true, false, '')",
            "select query_to_xml_and_xmlschema('select * from secrets', true, false, '')",
            "select table_to_xml('secrets', true, false, '')",
            "select cursor_to_xml('c', 10, true, false, '')",
            "select schema_to_xml('public', true, false, '')",
            "select database_to_xml(true, false, '')",
            "select dblink('dbname=other', 'select * from secrets')",
            "select ts_stat('select body from secrets')",
            "select pg_catalog.query_to_xml('select * from secrets', true, false, '')",
            (
                "select name from dealers "
                "where exists (select table_to_xml('secrets', true, false, ''))"
            ),
        ],
    )
    def test_is_rejected(self, sql):
        _rejected(sql)

    def test_the_rejection_names_the_function_so_the_model_can_correct_it(self):
        assert "table_to_xml" in _rejected("select table_to_xml('secrets', true, false, '')")

    def test_an_ordinary_function_is_still_accepted(self):
        _ok("select date_trunc('month', created_at), count(*) from dealers group by 1")

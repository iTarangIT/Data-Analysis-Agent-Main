"""The file connector, and the lockdown that is the first of its two security layers.

The guard's table allowlist is the second. These tests cover the engine layer: after ingest the
connection cannot reach the filesystem at all, however the query is written.
"""

from pathlib import Path

import pytest

from app.connectors.duckdb import DuckDBConnector, FileSource, ingest_upload
from app.services.errors import DomainError

CSV = "region,product,units,revenue_inr\nWest,Cell,10,2500.50\nEast,Pack,4,1800.00\n"


@pytest.fixture
def sales(tmp_path) -> list[FileSource]:
    src = tmp_path / "Q3 sales.csv"
    src.write_text(CSV, encoding="utf-8")
    return ingest_upload(src, tmp_path / "out", src.name)


@pytest.fixture
def connector(sales) -> DuckDBConnector:
    return DuckDBConnector("t_a", sales)


class TestIngest:
    def test_a_csv_becomes_one_parquet_table(self, sales, tmp_path):
        assert [s.table for s in sales] == ["q3_sales"]
        assert Path(sales[0].path).exists()
        assert Path(sales[0].path).suffix == ".parquet"

    def test_the_table_name_is_derived_not_taken_from_the_filename(self, tmp_path):
        src = tmp_path / "weird name!! 2026.csv"
        src.write_text(CSV, encoding="utf-8")

        sources = ingest_upload(src, tmp_path / "out", src.name)

        assert sources[0].table == "weird_name_2026"

    def test_a_name_that_would_not_be_an_identifier_is_prefixed(self, tmp_path):
        src = tmp_path / "2026 report.csv"
        src.write_text(CSV, encoding="utf-8")

        assert ingest_upload(src, tmp_path / "out", src.name)[0].table == "t_2026_report"

    def test_every_sheet_of_a_spreadsheet_becomes_a_table(self, tmp_path):
        """Answering from the first sheet and silently ignoring the rest is the worst available
        failure for a spreadsheet-only customer."""
        import pandas as pd

        src = tmp_path / "book.xlsx"
        with pd.ExcelWriter(src) as writer:
            pd.DataFrame({"a": [1, 2]}).to_excel(writer, sheet_name="Sales", index=False)
            pd.DataFrame({"b": [3]}).to_excel(writer, sheet_name="Returns 2026", index=False)

        sources = ingest_upload(src, tmp_path / "out", src.name)

        assert sorted(s.table for s in sources) == ["returns_2026", "sales"]

    def test_an_empty_file_is_refused_with_a_readable_reason(self, tmp_path):
        import pandas as pd

        src = tmp_path / "empty.xlsx"
        with pd.ExcelWriter(src) as writer:
            pd.DataFrame().to_excel(writer, sheet_name="Blank", index=False)

        with pytest.raises(DomainError, match="no readable rows"):
            ingest_upload(src, tmp_path / "out", src.name)


class TestSchema:
    def test_it_lists_the_uploaded_tables(self, connector):
        assert connector.list_tables() == ["q3_sales"]

    def test_it_reads_the_uploaded_columns_in_file_order(self, connector):
        (table,) = connector.read_tables(["q3_sales"])

        assert table.name == "q3_sales"
        assert [c.name for c in table.columns] == ["region", "product", "units", "revenue_inr"]

    def test_types_are_sniffed_once_at_ingest(self, connector):
        (table,) = connector.read_tables(["q3_sales"])
        types = {c.name: c.type for c in table.columns}

        assert types["units"] == "BIGINT"
        assert types["region"] == "VARCHAR"

    def test_a_table_the_file_does_not_hold_is_not_invented(self, connector):
        assert [t.name for t in connector.read_tables(["q3_sales", "elsewhere"])] == ["q3_sales"]


class TestQuerying:
    def test_it_answers_a_question_about_the_file(self, connector):
        cols, rows = connector.run_select("select sum(units) as total from q3_sales", 10)

        assert cols == ["total"]
        assert rows == [(14,)]

    def test_rows_are_capped(self, connector):
        _, rows = connector.run_select("select * from q3_sales", 1)

        assert len(rows) == 1


class TestLockdown:
    """After ingest the process cannot touch the filesystem, whatever the guard thinks. This is
    the analogue of `default_transaction_read_only=on` on the Postgres connector."""

    @pytest.mark.parametrize(
        "sql",
        [
            "select * from read_csv_auto('C:/Windows/win.ini')",
            "select * from read_parquet('C:/x.parquet')",
            "select * from read_text('C:/Windows/win.ini')",
            "select * from read_blob('C:/Windows/win.ini')",
            "install httpfs",
            "copy q3_sales to 'C:/leak.csv'",
        ],
    )
    def test_the_engine_refuses_to_reach_the_filesystem(self, connector, sql):
        with pytest.raises(Exception, match=r"(?i)permission|not allowed|denied"):
            connector.run_select(sql, 10)

    def test_attaching_another_database_is_refused(self, connector, tmp_path):
        with pytest.raises(Exception, match=r"(?i)permission"):
            connector.run_select(f"attach '{(tmp_path / 'o.db').as_posix()}' as o", 10)

    def test_the_lockdown_cannot_be_lifted(self, connector):
        with pytest.raises(Exception, match=r"(?i)lock"):
            connector.run_select("set enable_external_access=true", 10)

    def test_a_table_name_that_is_not_an_identifier_never_reaches_create_table(self, sales):
        bad = [FileSource(table="sales; drop table x", path=sales[0].path)]

        with pytest.raises(ValueError, match="unsafe table name"):
            DuckDBConnector("t_a", bad)


class TestProtocol:
    def test_it_is_a_sql_connector_that_parses_duckdb(self, connector):
        assert connector.kind == "file"
        assert connector.dialect == "duckdb"
        assert hasattr(connector, "run_select")

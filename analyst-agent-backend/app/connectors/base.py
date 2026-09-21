from typing import Any, Protocol

from app.catalog.types import TableDef


class Connector(Protocol):
    """A customer data source. Every implementation is read-only by construction."""

    kind: str


class CatalogReader(Connector, Protocol):
    def list_tables(self) -> list[str]: ...

    def read_tables(self, names: list[str]) -> list[TableDef]: ...

    def table_stats(self, names: list[str]) -> dict[str, dict[str, Any]]: ...


class SqlConnector(Connector, Protocol):
    """A source the query tool reaches with SQL: Postgres, or DuckDB over an uploaded file."""

    dialect: str

    def run_select(self, sql: str, max_rows: int) -> tuple[list[str], list[tuple]]: ...

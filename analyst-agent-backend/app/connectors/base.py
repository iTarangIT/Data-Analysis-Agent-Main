from typing import Any, Protocol


class Connector(Protocol):
    """A customer data source. Every implementation is read-only by construction."""

    kind: str

    def describe_schema(self) -> dict[str, Any]: ...


class SqlConnector(Connector, Protocol):
    """A source the query tool reaches with SQL. DuckDB joins Postgres here in phase 5."""

    dialect: str

    def run_select(self, sql: str, max_rows: int) -> tuple[list[str], list[tuple]]: ...


class WebSource(Connector, Protocol):
    """A dashboard read by driving a browser. It has no query language, so no `run_select`."""

    def fetch_rows(self, max_rows: int) -> tuple[list[str], list[tuple]]: ...

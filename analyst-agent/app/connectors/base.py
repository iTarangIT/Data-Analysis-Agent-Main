from typing import Any, Protocol


class Connector(Protocol):
    """A customer data source. Every implementation is read-only by construction."""

    kind: str

    def describe_schema(self) -> dict[str, Any]: ...


class SqlConnector(Connector, Protocol):
    """A source the query tool reaches with SQL. DuckDB joins Postgres here in phase 5."""

    dialect: str

    def run_select(self, sql: str, max_rows: int) -> tuple[list[str], list[tuple]]: ...

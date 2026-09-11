from typing import Any, Protocol


class Connector(Protocol):
    """A customer data source. Every implementation is read-only by construction."""

    kind: str

    def describe_schema(self) -> dict[str, Any]: ...

    def run_select(self, sql: str, max_rows: int) -> tuple[list[str], list[tuple]]: ...

    def test(self) -> bool: ...

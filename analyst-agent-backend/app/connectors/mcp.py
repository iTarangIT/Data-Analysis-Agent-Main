from typing import Any

from app import mcp_client
from app.catalog.types import TableDef


class McpConnector:
    kind = "postgres"
    dialect = "postgres"

    def __init__(self, tenant_id: str, connection_id: str):
        self.tenant_id = tenant_id
        self.connection_id = connection_id

    def _call(self, tool: str, args: dict[str, Any]) -> Any:
        return mcp_client.call(self.tenant_id, self.connection_id, tool, args)

    def list_tables(self) -> list[str]:
        return self._call("list_tables", {})

    def read_tables(self, names: list[str]) -> list[TableDef]:
        return [TableDef.model_validate(t) for t in self._call("read_tables", {"names": names})]

    def table_stats(self, names: list[str]) -> dict[str, dict[str, Any]]:
        return self._call("table_stats", {"names": names})

    def run_select(self, sql: str, max_rows: int) -> tuple[list[str], list[tuple]]:
        result = self._call("run_select", {"sql": sql, "max_rows": max_rows})
        if result.get("error"):
            raise RuntimeError(result["error"])
        return result["columns"], [tuple(r) for r in result["rows"]]

from typing import Any

from app.config import get_settings
from app.workers.web_session import fetch_dashboard_json


class WebConnector:
    """One tenant's web dashboard, read by driving a browser session that belongs to them alone.

    Satisfies `Connector` but not `SqlConnector`: a dashboard has no query language, so there is
    no `run_select` to implement honestly.
    """

    kind = "web"

    def __init__(self, tenant_id: str, connection_id: str, secret: dict[str, str]) -> None:
        self.tenant_id = tenant_id
        self.connection_id = connection_id
        self._secret = secret
        self._data_url_match = secret.get("data_url_match") or get_settings().web_data_url_match
        self._payload: list[dict[str, Any]] | None = None

    def _load(self) -> list[dict[str, Any]]:
        # The connector is rebuilt per request by `connector_for`, so this memo never outlives
        # one run. It exists because describe_schema and the tool would otherwise sign in twice.
        if self._payload is None:
            self._payload = fetch_dashboard_json(
                self.tenant_id, self.connection_id, self._secret, self._data_url_match
            )
        return self._payload

    def describe_schema(self, sample_rows: int | None = None) -> dict[str, Any]:
        """The same shape `PostgresConnector` returns, so the tool description, the schema cache
        and the six-hour refresh all work unchanged.

        Unlike a database this cannot be introspected without fetching, so the schema costs a
        real browser session. `_load` is why it costs only one per run.
        """
        if sample_rows is None:
            sample_rows = get_settings().schema_sample_rows

        payload = self._load()
        columns = sorted({k for row in payload for k in row})
        types = {c: _type_of(payload, c) for c in columns}
        sample = [[str(row.get(c)) for c in columns] for row in payload[:sample_rows]]
        return {
            "tables": [
                {
                    "name": "dashboard",
                    "columns": [{"name": c, "type": types[c]} for c in columns],
                    "sample": sample,
                }
            ]
        }

    def fetch_rows(self, max_rows: int) -> tuple[list[str], list[tuple]]:
        payload = self._load()
        columns = sorted({k for row in payload for k in row})
        rows = [tuple(row.get(c) for c in columns) for row in payload[:max_rows]]
        return columns, rows


def _type_of(payload: list[dict[str, Any]], column: str) -> str:
    for row in payload:
        value = row.get(column)
        if value is not None:
            return type(value).__name__
    return "str"

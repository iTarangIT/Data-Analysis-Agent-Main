import json
from typing import Any

from langchain.tools import tool
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.agent.nodes.sql_guard import validate_sql
from app.agent.prompts import QUERY_TOOL_DESC, QUERY_TOOL_SQL_ARG
from app.config import get_settings
from app.connectors.base import SqlConnector

TOOL_NAME = "query_database"

# Enough rows for the model to answer from, without putting a full result set in its context.
# The complete result travels separately as the tool's artifact.
PREVIEW_ROWS = 50


class QueryDatabaseArgs(BaseModel):
    sql: str = Field(description=QUERY_TOOL_SQL_ARG)


def _table_list(schema: dict[str, Any]) -> str:
    """The tool carries the schema so it is usable on its own, not only from the agent."""
    parts = []
    for t in schema.get("tables", []):
        cols = ", ".join(f"{c['name']} {c['type']}" for c in t["columns"])
        parts.append(f"TABLE {t['name']} ({cols})")
        if t.get("sample"):
            parts.append(f"  sample rows: {json.dumps(t['sample'][:3])}")
    return "\n".join(parts)


def make_query_tool(connector: SqlConnector, schema: dict[str, Any]) -> BaseTool:
    allowed = {t["name"] for t in schema.get("tables", [])}

    @tool(
        TOOL_NAME,
        description=QUERY_TOOL_DESC.format(tables=_table_list(schema)),
        args_schema=QueryDatabaseArgs,
        response_format="content_and_artifact",
    )
    def query_database(sql: str) -> tuple[str, dict[str, Any]]:
        max_rows = get_settings().max_rows

        safe_sql, err = validate_sql(sql, allowed, max_rows, connector.dialect)
        if err:
            return f"Query rejected: {err}. Rewrite it.", {"error": err}

        try:
            # One row beyond the cap tells us whether the result was truncated.
            cols, rows = connector.run_select(safe_sql, max_rows + 1)
        except Exception as e:
            message = f"database error: {e}"
            return f"Query failed: {message}. Rewrite it.", {"error": message}

        capped = [list(r) for r in rows[:max_rows]]
        result = {
            "sql": safe_sql,
            "columns": cols,
            "rows": capped,
            "truncated": len(rows) > max_rows,
        }
        preview = json.dumps(
            {"columns": cols, "rows": capped[:PREVIEW_ROWS], "row_count": len(capped)},
            default=str,
        )
        return preview, result

    return query_database

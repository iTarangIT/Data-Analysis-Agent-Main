"""LangChain tools the model is allowed to call.

A tool is callable by a model, so it cannot assume the graph guarded the query first. Every
tool that touches a customer database runs `validate_sql` itself. That keeps the guarantee
that no model-written SQL reaches a database unguarded, whether it arrives through the graph
or through a direct tool call.
"""

import json
from typing import Any

from langchain.tools import tool
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.agent.nodes.sql_guard import validate_sql
from app.config import get_settings
from app.connectors.base import Connector

TOOL_NAME = "query_database"

_DESCRIPTION = """Run one read-only SQL SELECT against the customer's database and return the
rows. Use this for any question about historic or stored data.

Only these tables and columns exist, and only SELECT is permitted:
{tables}

Queries run under a short statement timeout. Constrain time columns, filter by entity where
the question names one, and prefer summary tables over raw readings."""


class QueryDatabaseArgs(BaseModel):
    sql: str = Field(description="One PostgreSQL SELECT statement. No prose, no code fences.")


def _table_list(schema: dict[str, Any]) -> str:
    """The tool carries the schema so it is usable on its own, not only from the graph."""
    parts = []
    for t in schema.get("tables", []):
        cols = ", ".join(f"{c['name']} {c['type']}" for c in t["columns"])
        parts.append(f"TABLE {t['name']} ({cols})")
        if t.get("sample"):
            parts.append(f"  sample rows: {json.dumps(t['sample'][:3])}")
    return "\n".join(parts)


def make_query_tool(connector: Connector, schema: dict[str, Any]) -> BaseTool:
    allowed = {t["name"] for t in schema.get("tables", [])}

    @tool(
        TOOL_NAME,
        description=_DESCRIPTION.format(tables=_table_list(schema)),
        args_schema=QueryDatabaseArgs,
    )
    def query_database(sql: str) -> dict[str, Any]:
        max_rows = get_settings().max_rows
        safe_sql, err = validate_sql(sql, allowed, max_rows)
        if err:
            return {"error": err}
        try:
            # One row beyond the cap tells us whether the result was truncated.
            cols, rows = connector.run_select(safe_sql, max_rows + 1)
        except Exception as e:
            return {"error": f"database error: {e}"}
        return {
            "sql": safe_sql,
            "columns": cols,
            "rows": [list(r) for r in rows[:max_rows]],
            "truncated": len(rows) > max_rows,
        }

    return query_database

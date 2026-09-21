import json
import time
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, create_model

from app.agent import memory
from app.agent.context import RunContext
from app.agent.nodes.sql_guard import validate_sql
from app.agent.prompts import (
    DIALECTS,
    QUERY_TOOL_DESC,
    QUERY_TOOL_SQL_ARG,
    QUERY_TOOL_WHAT_ARG,
    QUERY_TOOL_WHY_ARG,
    REMEMBER_DEFINITION_ARG,
    REMEMBER_TERM_ARG,
    REMEMBER_TOOL_DESC,
)
from app.agent.schema_context import render_relationships, render_tables
from app.catalog.types import Catalog
from app.config import get_settings
from app.connectors.base import SqlConnector

TOOL_NAME = "query_database"
REMEMBER_TOOL_NAME = "remember"

# Enough rows for the model to answer from, without putting a full result set in its context.
# The complete result travels separately as the tool's artifact.
PREVIEW_ROWS = 50


class RememberArgs(BaseModel):
    term: str = Field(description=REMEMBER_TERM_ARG)
    definition: str = Field(description=REMEMBER_DEFINITION_ARG)


def make_query_tool(connector: SqlConnector, catalog: Catalog) -> BaseTool:
    # The catalog holds only the tables a person chose, so it is the allowlist as well as the
    # description: a table left out is one the model is neither told about nor allowed to query.
    allowed = catalog.table_names
    dialect = DIALECTS[connector.dialect]
    args = create_model(
        "QueryDatabaseArgs",
        sql=(str, Field(description=QUERY_TOOL_SQL_ARG.format(dialect=dialect))),
        # Defaulted, so a model that leaves them out loses a line of explanation rather than a turn
        # to a validation error.
        what=(str, Field(default="", description=QUERY_TOOL_WHAT_ARG)),
        why=(str, Field(default="", description=QUERY_TOOL_WHY_ARG)),
    )

    @tool(
        TOOL_NAME,
        description=QUERY_TOOL_DESC.format(
            tables=render_tables(catalog), relationships=render_relationships(catalog)
        ),
        args_schema=args,
        response_format="content_and_artifact",
    )
    def query_database(
        sql: str, runtime: ToolRuntime[RunContext], what: str = "", why: str = ""
    ) -> tuple[str, dict[str, Any]]:
        max_rows = get_settings().max_rows
        explained = {"what": what, "why": why}

        safe_sql, err = validate_sql(sql, allowed, max_rows, connector.dialect)
        if err:
            # The artifact carries the rejected SQL so a later success can be recorded against it
            # as a correction.
            return f"Query rejected: {err}.{_prior_fix(runtime, sql)} Rewrite it.", {
                "error": err,
                "at": "guard",
                "sql": sql,
                **explained,
            }

        t0 = time.perf_counter()
        try:
            # One row beyond the cap tells us whether the result was truncated.
            cols, rows = connector.run_select(safe_sql, max_rows + 1)
        except Exception as e:
            message = f"database error: {e}"
            return f"Query failed: {message}. Rewrite it.", {
                "error": message,
                "at": "database",
                "sql": sql,
                **explained,
            }

        capped = [list(r) for r in rows[:max_rows]]
        result = {
            "sql": safe_sql,
            "columns": cols,
            "rows": capped,
            "truncated": len(rows) > max_rows,
            "ms": int((time.perf_counter() - t0) * 1000),
            **explained,
        }
        preview = json.dumps(
            {"columns": cols, "rows": capped[:PREVIEW_ROWS], "row_count": len(capped)},
            default=str,
        )
        return preview, result

    return query_database


def _prior_fix(runtime: ToolRuntime[RunContext], sql: str) -> str:
    """What worked the last time this exact query was refused, if it has been refused before.

    The rejection string is the only channel back to the model, so a remembered correction has to
    travel in it rather than in the prompt.
    """
    if runtime.store is None:
        return ""
    past = memory.recall_correction(runtime.store, runtime.context, sql)
    return f" This was refused before and corrected to: {past['corrected']}." if past else ""


@tool(REMEMBER_TOOL_NAME, description=REMEMBER_TOOL_DESC, args_schema=RememberArgs)
def remember(term: str, definition: str, runtime: ToolRuntime[RunContext]) -> str:
    """Records a definition against the connection, never against an id the model supplies."""
    memory.remember_definition(runtime.store, runtime.context, term, definition)
    return f"Noted - {term}: {definition}"


def make_tools(connector: SqlConnector, catalog: Catalog, with_memory: bool) -> list[BaseTool]:
    tools = [make_query_tool(connector, catalog)]
    if with_memory:
        tools.append(remember)
    return tools

import json
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, create_model

from app.agent import memory
from app.agent.context import RunContext
from app.agent.nodes.sql_guard import validate_sql
from app.agent.prompts import (
    DIALECTS,
    FORECAST_GRAIN_ARG,
    FORECAST_HORIZON_ARG,
    FORECAST_KIND_ARG,
    FORECAST_SQL_ARG,
    FORECAST_TIME_ARG,
    FORECAST_TOOL_DESC,
    FORECAST_VALUE_ARG,
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
from app.forecasting.preprocessing import ForecastInputError, Grain, Kind, prepare_series
from app.forecasting.service import ForecastEngineError, ForecastService

TOOL_NAME = "query_database"
FORECAST_TOOL_NAME = "forecast_series"
REMEMBER_TOOL_NAME = "remember"

# Enough rows for the model to answer from, without putting a full result set in its context.
# The complete result travels separately as the tool's artifact.
PREVIEW_ROWS = 50


class RememberArgs(BaseModel):
    term: str = Field(description=REMEMBER_TERM_ARG)
    definition: str = Field(description=REMEMBER_DEFINITION_ARG)


@dataclass(frozen=True)
class _Selected:
    sql: str
    columns: list[str]
    rows: list
    ms: int


@dataclass(frozen=True)
class _Refused:
    content: str
    artifact: dict[str, Any]


def _select(
    connector: SqlConnector,
    allowed: set[str],
    sql: str,
    cap: int,
    runtime: ToolRuntime[RunContext],
    explained: dict[str, str],
) -> _Selected | _Refused:
    """Guard, then run, fetching one row past `cap` so the caller can tell it was truncated.

    Shared by both tools, so a refusal reads the same to the model whichever tool it called.
    """
    safe_sql, err = validate_sql(sql, allowed, cap, connector.dialect)
    if err:
        # The artifact carries the rejected SQL so a later success can be recorded against it
        # as a correction.
        return _Refused(
            f"Query rejected: {err}.{_prior_fix(runtime, sql)} Rewrite it.",
            {"error": err, "at": "guard", "sql": sql, **explained},
        )

    t0 = time.perf_counter()
    try:
        cols, rows = connector.run_select(safe_sql, cap + 1)
    except Exception as e:
        message = f"database error: {e}"
        return _Refused(
            f"Query failed: {message}. Rewrite it.",
            {"error": message, "at": "database", "sql": sql, **explained},
        )
    return _Selected(safe_sql, cols, rows, int((time.perf_counter() - t0) * 1000))


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

        got = _select(connector, allowed, sql, max_rows, runtime, explained)
        if isinstance(got, _Refused):
            return got.content, got.artifact

        capped = [list(r) for r in got.rows[:max_rows]]
        result = {
            "sql": got.sql,
            "columns": got.columns,
            "rows": capped,
            "truncated": len(got.rows) > max_rows,
            "ms": got.ms,
            **explained,
        }
        preview = json.dumps(
            {"columns": got.columns, "rows": capped[:PREVIEW_ROWS], "row_count": len(capped)},
            default=str,
        )
        return preview, result

    return query_database


def make_forecast_tool(
    connector: SqlConnector, catalog: Catalog, forecaster: ForecastService, today: date
) -> BaseTool:
    allowed = catalog.table_names
    args = create_model(
        "ForecastSeriesArgs",
        sql=(str, Field(description=FORECAST_SQL_ARG.format(dialect=DIALECTS[connector.dialect]))),
        time_column=(str, Field(description=FORECAST_TIME_ARG)),
        value_column=(str, Field(description=FORECAST_VALUE_ARG)),
        grain=(Grain, Field(description=FORECAST_GRAIN_ARG)),
        # No upper bound here: the service knows how far this history can reach and says so
        # in words the model can pass on, which a schema error would not.
        horizon=(int, Field(ge=1, description=FORECAST_HORIZON_ARG)),
        kind=(Kind, Field(description=FORECAST_KIND_ARG)),
        what=(str, Field(default="", description=QUERY_TOOL_WHAT_ARG)),
        why=(str, Field(default="", description=QUERY_TOOL_WHY_ARG)),
    )

    @tool(
        FORECAST_TOOL_NAME,
        description=FORECAST_TOOL_DESC,
        args_schema=args,
        response_format="content_and_artifact",
    )
    def forecast_series(
        sql: str,
        time_column: str,
        value_column: str,
        grain: Grain,
        horizon: int,
        kind: Kind,
        runtime: ToolRuntime[RunContext],
        what: str = "",
        why: str = "",
    ) -> tuple[str, dict[str, Any]]:
        # The same cap as the query tool, because the MCP server applies its own `max_rows` to
        # every Postgres query regardless of what the caller asks for.
        max_rows = get_settings().max_rows
        explained = {"what": what, "why": why}

        got = _select(connector, allowed, sql, max_rows, runtime, explained)
        if isinstance(got, _Refused):
            return got.content, got.artifact

        rows = got.rows[:max_rows]
        capped = len(got.rows) > max_rows
        try:
            series = prepare_series(
                got.columns, rows, time_column, value_column, grain, kind, today, capped
            )
            forecast = forecaster.forecast(series, horizon)
        except ForecastInputError as e:
            return _cannot_forecast(e.code, e.message, e.fixable, got.sql, explained)
        except ForecastEngineError as e:
            return _cannot_forecast(
                "model_failed", f"the forecasting model failed: {e}", False, got.sql, explained
            )

        result = {
            "sql": got.sql,
            "columns": got.columns,
            "rows": [list(r) for r in rows],
            "truncated": capped,
            "ms": got.ms,
            **explained,
            "forecast": {
                **forecast.chart_payload(),
                "time_column": time_column,
                "value_column": value_column,
            },
        }
        return json.dumps({"forecast": forecast.summary()}), result

    return forecast_series


def _cannot_forecast(
    code: str, message: str, fixable: bool, sql: str, explained: dict[str, str]
) -> tuple[str, dict[str, Any]]:
    content = json.dumps({"error": {"code": code, "message": message, "fixable": fixable}})
    return content, {"error": message, "at": "forecast", "sql": sql, **explained}


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


def make_tools(
    connector: SqlConnector,
    catalog: Catalog,
    with_memory: bool,
    forecaster: ForecastService | None = None,
    today: date | None = None,
) -> list[BaseTool]:
    tools = [make_query_tool(connector, catalog)]
    if forecaster is not None:
        tools.append(make_forecast_tool(connector, catalog, forecaster, today or date.today()))
    if with_memory:
        tools.append(remember)
    return tools

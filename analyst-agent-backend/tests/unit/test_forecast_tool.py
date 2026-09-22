"""The forecast tool: the query tool's guard, then the forecasting service, as one call."""

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
from langchain.tools import ToolRuntime

from app.agent.context import RunContext
from app.agent.tools import FORECAST_TOOL_NAME, make_forecast_tool, make_tools
from app.catalog.types import Catalog, CatalogTable, Column, TableDef
from app.config import get_settings
from app.forecasting.engine import EngineForecast
from app.forecasting.service import ForecastService

CONTEXT = RunContext(tenant_id="t_test", connection_id="c1", run_id="r1", thread_id="th1")
TODAY = date(2026, 9, 22)
CATALOG = Catalog(
    tables=[
        CatalogTable(
            definition=TableDef(
                name="sales",
                columns=[Column(name="month", type="date"), Column(name="revenue", type="numeric")],
            )
        )
    ]
)


class FlatEngine:
    """Forecasts the last value, with a range of one either side."""

    name = "flat"
    max_context = 1024
    max_horizon = 256

    def predict(self, values, horizon):
        mean = np.full(horizon, values[-1])
        return EngineForecast(mean=mean, lower=mean - 1, upper=mean + 1)


class FakeConnector:
    kind = "postgres"
    dialect = "postgres"

    def __init__(self, rows):
        self.rows = rows
        self.executed: list[str] = []

    def run_select(self, sql, max_rows):
        self.executed.append(sql)
        return ["month", "revenue"], self.rows[:max_rows]


def months(n: int, newest_first: bool = True) -> list[tuple]:
    periods = pd.period_range(end="2026-08", periods=n, freq="M")
    rows = [(p.start_time.date().isoformat(), 100 + i) for i, p in enumerate(periods)]
    return rows[::-1] if newest_first else rows


def call(rows, **args):
    tool = make_forecast_tool(FakeConnector(rows), CATALOG, ForecastService(FlatEngine()), TODAY)
    base = {
        "sql": "select month, revenue from sales order by month desc",
        "time_column": "month",
        "value_column": "revenue",
        "grain": "month",
        "horizon": 3,
        "kind": "total",
        "what": "Totalled revenue by month.",
        "why": "You asked for a forecast.",
    }
    runtime = ToolRuntime(
        state={}, context=CONTEXT, config={}, stream_writer=lambda _: None,
        tool_call_id="c1", store=None,
    )  # fmt: skip
    msg = tool.invoke(
        {
            "name": tool.name,
            "args": {**base, **args, "runtime": runtime},
            "id": "c1",
            "type": "tool_call",
        }
    )
    content = json.loads(msg.content) if msg.content.startswith("{") else msg.content
    return content, msg.artifact


class TestContract:
    def test_the_model_must_give_everything_but_the_explanation(self):
        tool = make_forecast_tool(FakeConnector([]), CATALOG, ForecastService(FlatEngine()), TODAY)

        assert tool.name == FORECAST_TOOL_NAME
        assert sorted(tool.tool_call_schema.model_json_schema()["required"]) == [
            "grain", "horizon", "kind", "sql", "time_column", "value_column",
        ]  # fmt: skip

    def test_it_is_offered_only_when_a_model_is_loaded(self):
        connector = FakeConnector([])

        without = make_tools(connector, CATALOG, with_memory=False)
        with_model = make_tools(
            connector, CATALOG, with_memory=False,
            forecaster=ForecastService(FlatEngine()), today=TODAY,
        )  # fmt: skip

        assert [t.name for t in without] == ["query_database"]
        assert [t.name for t in with_model] == ["query_database", FORECAST_TOOL_NAME]


class TestAForecast:
    def test_the_model_is_told_the_forecast(self):
        content, _ = call(months(12))

        forecast = content["forecast"]
        assert [p["period"] for p in forecast["points"]] == ["2026-09", "2026-10", "2026-11"]
        assert forecast["points"][0] == {
            "period": "2026-09", "forecast": 111.0, "low": 110.0, "high": 112.0,
        }  # fmt: skip
        assert forecast["history"]["to"] == "2026-08" and forecast["history"]["periods"] == 12

    def test_the_artifact_carries_what_the_stream_needs(self):
        _, artifact = call(months(12))

        assert artifact["sql"].upper().startswith("SELECT") and "LIMIT" in artifact["sql"].upper()
        assert (artifact["what"], artifact["why"]) == (
            "Totalled revenue by month.", "You asked for a forecast.",
        )  # fmt: skip
        assert artifact["columns"] == ["month", "revenue"] and len(artifact["rows"]) == 12
        assert artifact["forecast"]["time_column"] == "month"
        assert artifact["forecast"]["value_column"] == "revenue"
        assert artifact["forecast"]["points"][0] == ["2026-09", 111.0, 110.0, 112.0]


class TestRefusals:
    def test_the_guard_refuses_exactly_as_it_does_for_the_query_tool(self):
        content, artifact = call(months(12), sql="delete from sales")

        assert content.startswith("Query rejected:")
        assert artifact["at"] == "guard"

    def test_history_the_data_cannot_support_is_explained_not_retried(self):
        content, artifact = call(months(5))

        assert content["error"]["code"] == "insufficient_history"
        assert content["error"]["fixable"] is False
        assert artifact["at"] == "forecast" and artifact["error"]

    def test_too_far_ahead_is_explained_not_retried(self):
        content, _ = call(months(12), horizon=24)

        assert content["error"]["code"] == "horizon_too_long"
        assert content["error"]["fixable"] is False


class TestTheRowCap:
    @pytest.fixture(autouse=True)
    def small_cap(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "max_rows", 12)

    def test_newest_first_the_latest_periods_are_used(self):
        content, artifact = call(months(20))

        assert content["forecast"]["history"]["capped"] is True
        assert content["forecast"]["history"]["to"] == "2026-08"
        assert artifact["truncated"] is True and len(artifact["rows"]) == 12

    def test_oldest_first_the_model_is_asked_to_reorder(self):
        content, artifact = call(months(20, newest_first=False))

        assert content["error"]["code"] == "wrong_order"
        assert content["error"]["fixable"] is True
        assert artifact["at"] == "forecast"

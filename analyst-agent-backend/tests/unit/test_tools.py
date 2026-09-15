import json

import pytest
from langchain_core.tools import BaseTool

from app.agent.tools import PREVIEW_ROWS, make_query_tool
from app.catalog.types import Catalog, CatalogTable, Column, TableDef

VEHICLES = CatalogTable(
    definition=TableDef(name="vehicles", columns=[Column(name="vehicleno", type="text")])
)
ALERTS = CatalogTable(
    definition=TableDef(name="alerts", columns=[Column(name="severity", type="text")])
)
CATALOG = Catalog(tables=[VEHICLES, ALERTS])


class FakeConnector:
    kind = "postgres"
    dialect = "postgres"

    def __init__(self, cols=("vehicleno",), rows=(("KA01",), ("KA02",))):
        self.cols, self.rows = list(cols), [tuple(r) for r in rows]
        self.executed: list[str] = []

    def run_select(self, sql, max_rows):
        self.executed.append(sql)
        return self.cols, self.rows[:max_rows]


@pytest.fixture
def connector():
    return FakeConnector()


@pytest.fixture
def tool(connector):
    return make_query_tool(connector, CATALOG)


def call(tool, sql: str | None = None):
    """Invoke as the agent does, so the structured artifact comes back on a ToolMessage."""
    args = {} if sql is None else {"sql": sql}
    msg = tool.invoke({"name": tool.name, "args": args, "id": "c1", "type": "tool_call"})
    return msg.content, msg.artifact


class TestToolContract:
    def test_it_is_a_real_langchain_tool(self, tool):
        assert isinstance(tool, BaseTool)

    def test_it_declares_a_single_sql_argument(self, tool):
        assert set(tool.args_schema.model_fields) == {"sql"}

    def test_its_description_names_the_tables_the_model_may_use(self, tool):
        assert "TABLE vehicles" in tool.description and "TABLE alerts" in tool.description


class TestGuardIsInsideTheTool:
    """The tool is callable by a model, so it cannot rely on the graph having guarded first."""

    @pytest.mark.parametrize(
        "sql",
        [
            "delete from vehicles",
            "update vehicles set vehicleno = 'x'",
            "drop table alerts",
            "select * into copies from vehicles",
            "select 1; delete from vehicles",
            "select * from pg_shadow",
        ],
    )
    def test_a_dangerous_query_is_refused_and_never_reaches_the_database(
        self, tool, connector, sql
    ):
        _, artifact = call(tool, sql)
        assert artifact["error"]
        assert connector.executed == [], "the connector was called despite the guard refusing"

    def test_the_refusal_explains_itself_so_the_model_can_correct(self, tool):
        content, artifact = call(tool, "select * from secrets")
        assert "secrets" in artifact["error"]
        assert "secrets" in content, "the model must see why, to correct it"

    def test_a_table_left_out_of_the_selection_is_neither_described_nor_queryable(self, connector):
        only_vehicles = make_query_tool(connector, Catalog(tables=[VEHICLES]))

        _, artifact = call(only_vehicles, "select severity from alerts")

        assert "alerts" not in only_vehicles.description
        assert "alerts" in artifact["error"]
        assert connector.executed == []


class TestExecution:
    def test_a_valid_select_returns_columns_and_rows(self, tool):
        _, artifact = call(tool, "select vehicleno from vehicles")
        assert artifact["columns"] == ["vehicleno"]
        assert artifact["rows"] == [["KA01"], ["KA02"]]
        assert artifact["truncated"] is False
        assert "error" not in artifact

    def test_the_row_cap_is_applied_before_execution(self, tool, connector):
        call(tool, "select vehicleno from vehicles")
        assert "LIMIT" in connector.executed[0].upper()

    def test_the_model_sees_a_preview_not_the_whole_result(self, connector):
        wide = FakeConnector(rows=[(f"KA{i:03}",) for i in range(PREVIEW_ROWS + 25)])
        content, artifact = call(make_query_tool(wide, CATALOG), "select vehicleno from vehicles")
        assert len(json.loads(content)["rows"]) == PREVIEW_ROWS
        assert len(artifact["rows"]) == PREVIEW_ROWS + 25, "the caller still gets every row"

    def test_a_database_failure_comes_back_as_an_error_not_an_exception(self):
        class Broken(FakeConnector):
            def run_select(self, sql, max_rows):
                raise RuntimeError("column does not exist")

        _, artifact = call(make_query_tool(Broken(), CATALOG), "select vehicleno from vehicles")
        assert "column does not exist" in artifact["error"]

    def test_truncation_is_reported(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "max_rows", 1, raising=False)
        conn = FakeConnector(rows=(("a",), ("b",), ("c",)))
        _, artifact = call(make_query_tool(conn, CATALOG), "select vehicleno from vehicles")
        assert artifact["truncated"] is True and artifact["rows"] == [["a"]]

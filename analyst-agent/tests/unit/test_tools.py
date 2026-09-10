import pytest
from langchain_core.tools import BaseTool

from app.agent.tools import make_query_tool

SCHEMA = {
    "tables": [
        {"name": "vehicles", "columns": [{"name": "vehicleno", "type": "TEXT"}], "sample": []},
        {"name": "alerts", "columns": [{"name": "severity", "type": "TEXT"}], "sample": []},
    ]
}


class FakeConnector:
    kind = "postgres"

    def __init__(self, cols=("vehicleno",), rows=(("KA01",), ("KA02",))):
        self.cols, self.rows = list(cols), [tuple(r) for r in rows]
        self.executed: list[str] = []

    def run_select(self, sql, max_rows):
        self.executed.append(sql)
        return self.cols, self.rows[:max_rows]

    def describe_schema(self):
        return SCHEMA

    def test(self):
        return True


@pytest.fixture
def connector():
    return FakeConnector()


@pytest.fixture
def tool(connector):
    return make_query_tool(connector, SCHEMA)


class TestToolContract:
    def test_it_is_a_real_langchain_tool(self, tool):
        assert isinstance(tool, BaseTool)

    def test_it_declares_a_single_sql_argument(self, tool):
        assert set(tool.args_schema.model_fields) == {"sql"}

    def test_its_description_names_the_tables_the_model_may_use(self, tool):
        assert "vehicles" in tool.description and "alerts" in tool.description


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
        out = tool.invoke({"sql": sql})
        assert out["error"]
        assert connector.executed == [], "the connector was called despite the guard refusing"

    def test_the_refusal_explains_itself_so_the_model_can_correct(self, tool):
        out = tool.invoke({"sql": "select * from secrets"})
        assert "secrets" in out["error"]


class TestExecution:
    def test_a_valid_select_returns_columns_and_rows(self, tool):
        out = tool.invoke({"sql": "select vehicleno from vehicles"})
        assert out["columns"] == ["vehicleno"]
        assert out["rows"] == [["KA01"], ["KA02"]]
        assert out["truncated"] is False
        assert "error" not in out

    def test_the_row_cap_is_applied_before_execution(self, tool, connector):
        tool.invoke({"sql": "select vehicleno from vehicles"})
        assert "LIMIT" in connector.executed[0].upper()

    def test_a_database_failure_comes_back_as_an_error_not_an_exception(self):
        class Broken(FakeConnector):
            def run_select(self, sql, max_rows):
                raise RuntimeError("column does not exist")

        out = make_query_tool(Broken(), SCHEMA).invoke({"sql": "select vehicleno from vehicles"})
        assert "column does not exist" in out["error"]

    def test_truncation_is_reported(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "max_rows", 1, raising=False)
        conn = FakeConnector(rows=(("a",), ("b",), ("c",)))
        out = make_query_tool(conn, SCHEMA).invoke({"sql": "select vehicleno from vehicles"})
        assert out["truncated"] is True and out["rows"] == [["a"]]

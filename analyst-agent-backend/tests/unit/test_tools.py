import json

import pytest
from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool
from langgraph.store.memory import InMemoryStore

from app.agent import memory
from app.agent.context import RunContext
from app.agent.tools import PREVIEW_ROWS, make_query_tool, make_tools, remember
from app.catalog.types import Catalog, CatalogTable, Column, TableDef
from app.connectors.duckdb import DuckDBConnector, ingest_upload

CONTEXT = RunContext(tenant_id="t_test", connection_id="c1", run_id="r1", thread_id="th1")

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


def runtime(store=None):
    """What ToolNode builds and hands the tool; nothing here reaches the model's schema."""
    return ToolRuntime(
        state={},
        context=CONTEXT,
        config={},
        stream_writer=lambda _: None,
        tool_call_id="c1",
        store=store,
    )


def call(tool, sql: str | None = None, store=None, **explained):
    """Invoke as the agent does, so the structured artifact comes back on a ToolMessage."""
    args = {"runtime": runtime(store), **explained}
    if sql is not None:
        args["sql"] = sql
    msg = tool.invoke({"name": tool.name, "args": args, "id": "c1", "type": "tool_call"})
    return msg.content, msg.artifact


class TestToolContract:
    def test_it_is_a_real_langchain_tool(self, tool):
        assert isinstance(tool, BaseTool)

    def test_it_declares_the_sql_and_its_plain_explanation(self, tool):
        assert set(tool.args_schema.model_fields) == {"sql", "what", "why"}

    @pytest.mark.parametrize("dialect,name", [("postgres", "PostgreSQL"), ("duckdb", "DuckDB")])
    def test_the_sql_argument_names_the_connectors_dialect(self, connector, dialect, name):
        connector.dialect = dialect

        schema = make_query_tool(connector, CATALOG).tool_call_schema.model_json_schema()

        assert schema["properties"]["sql"]["description"] == (
            f"One {name} SELECT statement. No prose, no code fences."
        )

    def test_only_the_sql_is_required_so_a_missing_explanation_costs_no_turn(self, tool):
        assert tool.tool_call_schema.model_json_schema()["required"] == ["sql"]

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

    @pytest.mark.parametrize(("held", "truncated"), [(3, True), (2, False)])
    def test_truncation_is_reported_only_when_rows_were_cut_off(
        self, monkeypatch, tmp_path, held, truncated
    ):
        """Through a real connector, so the guard's LIMIT decides how many rows come back. A
        fake that sliced its own rows passed while every real result was reported whole."""
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "max_rows", 2, raising=False)
        src = tmp_path / "vehicles.csv"
        src.write_text("vehicleno\n" + "".join(f"KA{i}\n" for i in range(held)), encoding="utf-8")
        conn = DuckDBConnector("t_test", ingest_upload(src, tmp_path / "out", src.name, set()))

        _, artifact = call(make_query_tool(conn, CATALOG), "select vehicleno from vehicles")

        assert artifact["truncated"] is truncated
        assert artifact["rows"] == [["KA0"], ["KA1"]]


EXPLAINED = {"what": "Lists every vehicle.", "why": "You asked which vehicles there are."}


class TestExplanation:
    """What the query was for travels beside it, so the run can be explained without asking the
    model a second time."""

    def test_a_result_carries_the_explanation_and_how_long_the_query_took(self, tool):
        _, artifact = call(tool, "select vehicleno from vehicles", **EXPLAINED)
        assert artifact["what"] == "Lists every vehicle."
        assert artifact["why"] == "You asked which vehicles there are."
        assert isinstance(artifact["ms"], int) and artifact["ms"] >= 0

    def test_a_refusal_carries_it_too_and_says_the_guard_refused(self, tool):
        _, artifact = call(tool, "delete from vehicles", **EXPLAINED)
        assert artifact["at"] == "guard"
        assert artifact["what"] == "Lists every vehicle."

    def test_a_database_failure_says_the_database_refused(self):
        class Broken(FakeConnector):
            def run_select(self, sql, max_rows):
                raise RuntimeError("column does not exist")

        _, artifact = call(make_query_tool(Broken(), CATALOG), "select vehicleno from vehicles")
        assert artifact["at"] == "database"

    def test_left_out_it_is_empty_rather_than_a_failed_call(self, tool):
        _, artifact = call(tool, "select vehicleno from vehicles")
        assert artifact["what"] == "" and artifact["why"] == ""
        assert "error" not in artifact


class TestRuntimeIsHiddenFromTheModel:
    """`runtime` is injected by ToolNode. If it ever showed up in the model-facing schema the
    model would try to supply it, and whatever it sent would be silently overwritten."""

    def test_the_model_is_offered_only_its_own_arguments(self, tool):
        assert set(tool.tool_call_schema.model_fields) == {"sql", "what", "why"}


class TestRememberedCorrections:
    """A refusal is the only channel back to the model, so a remembered fix has to ride in it."""

    def test_a_first_refusal_carries_no_hint(self, tool):
        content, _ = call(tool, "select severity from alerts", store=InMemoryStore())
        assert "refused before" not in content

    def test_a_refusal_seen_before_carries_the_query_that_worked(self, tool):
        store = InMemoryStore()
        memory.remember_correction(
            store, CONTEXT, "select * from secrets", "tables not allowed", "select 1 from vehicles"
        )

        content, artifact = call(tool, "select * from secrets", store=store)

        assert "select 1 from vehicles" in content
        assert artifact["error"], "the hint must not turn a refusal into a success"

    def test_the_rejected_sql_is_kept_so_a_later_success_can_be_paired_with_it(self, tool):
        _, artifact = call(tool, "delete from vehicles")
        assert artifact["sql"] == "delete from vehicles"

    def test_without_a_store_the_refusal_still_explains_itself(self, tool):
        content, artifact = call(tool, "select * from secrets", store=None)
        assert artifact["error"] and "secrets" in content


class TestRememberTool:
    def test_it_is_offered_only_when_there_is_somewhere_to_remember(self, connector):
        assert [t.name for t in make_tools(connector, CATALOG, with_memory=False)] == [
            "query_database"
        ]
        assert "remember" in [t.name for t in make_tools(connector, CATALOG, with_memory=True)]

    def test_a_definition_is_readable_on_a_later_run(self):
        store = InMemoryStore()

        remember.invoke(
            {
                "name": "remember",
                "args": {
                    "term": "net revenue",
                    "definition": "sales minus refunds",
                    "runtime": runtime(store),
                },
                "id": "c1",
                "type": "tool_call",
            }
        )

        assert "sales minus refunds" in memory.recall(store, CONTEXT)

    def test_it_is_filed_under_the_context_tenant_and_not_an_argument(self):
        store = InMemoryStore()
        remember.invoke(
            {
                "name": "remember",
                "args": {
                    "term": "churn",
                    "definition": "no order in 90 days",
                    "runtime": runtime(store),
                },
                "id": "c1",
                "type": "tool_call",
            }
        )

        other = RunContext(tenant_id="t_other", connection_id="c1", run_id="r2", thread_id="th2")
        assert memory.recall(store, other) == ""

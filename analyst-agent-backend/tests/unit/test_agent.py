"""The agent end to end with a scripted model, and the mapping onto the SSE contract."""

from unittest.mock import patch

import pytest
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from app.agent.graph import build_agent, recursion_limit
from app.services.runs import EventTranslator, RunOutcome

SCHEMA = {
    "tables": [
        {
            "name": "vehicles",
            "columns": [{"name": "vehicleno", "type": "TEXT"}, {"name": "owner", "type": "TEXT"}],
            "sample": [],
        }
    ]
}


class FakeToolModel(FakeMessagesListChatModel):
    """create_agent binds tools to the model, which the stock fake does not support."""

    def bind_tools(self, tools, **kwargs):
        return self


class FakeConnector:
    kind = "postgres"
    dialect = "postgres"

    def __init__(self, rows=(("KA01",), ("KA02",))):
        self.rows = [tuple(r) for r in rows]
        self.columns = ["vehicleno"]
        self.executed: list[str] = []

    def run_select(self, sql, max_rows):
        self.executed.append(sql)
        return self.columns, self.rows[:max_rows]

    def describe_schema(self):
        return SCHEMA

    def test(self):
        return True


def _tool_call(sql):
    return AIMessage(
        content="",
        tool_calls=[{"name": "query_database", "args": {"sql": sql}, "id": "c1"}],
    )


def _run(model, connector):
    outcome = RunOutcome()
    translator = EventTranslator(outcome)
    events = []
    with patch("app.agent.graph.get_llm", return_value=model):
        agent = build_agent(connector, SCHEMA)
        for chunk in agent.stream(
            {"messages": [("user", "how many vehicles")]},
            config={"recursion_limit": recursion_limit()},
            stream_mode="updates",
        ):
            for node, update in chunk.items():
                for msg in (update or {}).get("messages", []):
                    events.extend(translator.for_message(node, msg))
    return events, outcome


def _stages(events):
    return [e["data"]["stage"] for e in events if e["type"] == "status"]


class TestHappyPath:
    @pytest.fixture
    def result(self):
        model = FakeToolModel(
            responses=[_tool_call("select vehicleno from vehicles"), AIMessage(content="Two.")]
        )
        return _run(model, FakeConnector())

    def test_emits_every_stage_of_the_frozen_contract(self, result):
        events, _ = result
        assert _stages(events) == ["router", "sql_gen", "sql_guard", "db_exec", "answer"]

    def test_event_order_matches_the_contract(self, result):
        events, _ = result
        assert [e["type"] for e in events] == [
            "status",
            "status",
            "status",
            "sql",
            "status",
            "rows",
            "status",
            "token",
        ]

    def test_the_sql_reported_is_the_guarded_sql(self, result):
        events, _ = result
        sql = next(e for e in events if e["type"] == "sql")["data"]["sql"]
        assert sql.upper().startswith("SELECT") and "LIMIT" in sql.upper()

    def test_rows_carry_columns_and_truncation(self, result):
        events, _ = result
        rows = next(e for e in events if e["type"] == "rows")["data"]
        assert rows["columns"] == ["vehicleno"]
        assert rows["rows"] == [["KA01"], ["KA02"]]
        assert rows["truncated"] is False

    def test_the_outcome_records_what_the_run_row_needs(self, result):
        _, outcome = result
        assert outcome.tool == "sql"
        assert outcome.sql.upper().startswith("SELECT")
        assert len(outcome.rows) == 2
        assert outcome.answer == "Two."


class TestQuestionNeedingNoDatabase:
    def test_answers_without_touching_the_connector(self):
        model = FakeToolModel(responses=[AIMessage(content="I only answer data questions.")])
        connector = FakeConnector()
        events, outcome = _run(model, connector)

        assert _stages(events) == ["router", "answer"]
        assert outcome.tool == "clarify"
        assert outcome.sql is None
        assert connector.executed == []


class TestGuardRejection:
    def test_a_refused_query_is_retried_and_never_reaches_the_database(self):
        model = FakeToolModel(
            responses=[
                _tool_call("delete from vehicles"),
                _tool_call("select vehicleno from vehicles"),
                AIMessage(content="Two."),
            ]
        )
        connector = FakeConnector()
        events, outcome = _run(model, connector)

        assert _stages(events) == [
            "router",
            "sql_gen",
            "sql_guard",  # refused, so no sql or rows event
            "sql_gen",
            "sql_guard",
            "db_exec",
            "answer",
        ]
        assert len(connector.executed) == 1, "the refused statement reached the database"
        assert "DELETE" not in connector.executed[0].upper()
        assert outcome.answer == "Two."


class TestRecursionLimit:
    def test_it_allows_the_configured_number_of_tool_calls(self):
        from app.config import get_settings

        # A tool call is a model step plus a tool step, then one model step for the answer.
        assert recursion_limit() == 2 * get_settings().max_tool_calls + 1

    def test_it_leaves_room_for_more_than_one_query(self):
        # A model may legitimately query twice to answer one question; the first limit was
        # derived from max_sql_retries and cut runs off after three tool calls.
        assert recursion_limit() >= 2 * 3 + 1


class TestContentBlocks:
    """Gemini 3 returns a list of content blocks. Reading `.content` would put a Python repr
    of that list into the token event instead of the answer."""

    def test_the_answer_is_flattened_from_content_blocks(self):
        blocks = [{"type": "text", "text": "There are three dealers.", "extras": {"sig": "x"}}]
        model = FakeToolModel(responses=[AIMessage(content=blocks)])
        events, outcome = _run(model, FakeConnector())

        token = next(e for e in events if e["type"] == "token")
        assert token["data"]["text"] == "There are three dealers."
        assert outcome.answer == "There are three dealers."

    def test_a_plain_string_answer_still_works(self):
        model = FakeToolModel(responses=[AIMessage(content="Plain string.")])
        events, _ = _run(model, FakeConnector())
        assert next(e for e in events if e["type"] == "token")["data"]["text"] == "Plain string."


WEB_SCHEMA = {
    "tables": [
        {
            "name": "dashboard",
            "columns": [{"name": "vehicleno", "type": "str"}, {"name": "soc", "type": "int"}],
            "sample": [],
        }
    ]
}


class FakeDashboard:
    kind = "web"

    def fetch_rows(self, max_rows):
        return ["vehicleno", "soc"], [("KA01", 82), ("KA02", 61)][:max_rows]

    def describe_schema(self):
        return WEB_SCHEMA


def _run_web(model, connector):
    outcome = RunOutcome()
    translator = EventTranslator(outcome)
    events = []
    with patch("app.agent.graph.get_llm", return_value=model):
        agent = build_agent(connector, WEB_SCHEMA)
        for chunk in agent.stream(
            {"messages": [("user", "what does the dashboard show")]},
            config={"recursion_limit": recursion_limit()},
            stream_mode="updates",
        ):
            for node, update in chunk.items():
                for msg in (update or {}).get("messages", []):
                    events.extend(translator.for_message(node, msg))
    return events, outcome


class TestWebPath:
    @pytest.fixture
    def result(self):
        model = FakeToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "fetch_dashboard", "args": {}, "id": "w1"}],
                ),
                AIMessage(content="Two vehicles are shown."),
            ]
        )
        return _run_web(model, FakeDashboard())

    def test_it_reports_the_web_tool_stage(self, result):
        events, _ = result
        assert _stages(events) == ["router", "web_tool", "answer"]

    def test_the_stage_is_announced_before_the_browser_runs(self, result):
        events, _ = result
        # web_tool precedes rows, so the client is not left on `router` for the whole fetch.
        types = [e["type"] for e in events]
        assert types == ["status", "status", "rows", "chart", "status", "token"]

    def test_no_sql_is_ever_reported_for_a_dashboard(self, result):
        events, outcome = result
        assert "sql" not in [e["type"] for e in events]
        assert outcome.sql is None

    def test_the_rows_reach_the_client(self, result):
        events, outcome = result
        rows = next(e for e in events if e["type"] == "rows")["data"]
        assert rows["columns"] == ["vehicleno", "soc"]
        assert rows["rows"] == [["KA01", 82], ["KA02", 61]]
        assert outcome.tool == "web"

    def test_a_browser_failure_still_ends_in_an_answer(self):
        class Broken(FakeDashboard):
            def fetch_rows(self, max_rows):
                raise RuntimeError("login timed out")

        model = FakeToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "fetch_dashboard", "args": {}, "id": "w1"}],
                ),
                AIMessage(content="The dashboard could not be read."),
            ]
        )
        events, outcome = _run_web(model, Broken())

        assert _stages(events) == ["router", "web_tool", "answer"]
        assert "rows" not in [e["type"] for e in events]
        assert outcome.answer == "The dashboard could not be read."


class TestChartEvent:
    """`chart` is a payload, not a stage. Adding a stage would break the frozen sequence and put
    a second copy of the decision into the web client's state machine."""

    def _chartable(self):
        model = FakeToolModel(
            responses=[
                _tool_call("select vehicleno, soc from vehicles"),
                AIMessage(content="West leads."),
            ]
        )
        connector = FakeConnector(rows=(("KA01", 82), ("KA02", 61)))
        connector.columns = ["vehicleno", "soc"]
        return _run(model, connector)

    def test_a_chartable_result_emits_a_chart_after_the_rows(self):
        events, outcome = self._chartable()
        types = [e["type"] for e in events]

        assert types.index("chart") == types.index("rows") + 1
        assert outcome.chart == {"type": "bar", "x": "vehicleno", "y": ["soc"]}

    def test_the_stage_sequence_is_unchanged(self):
        events, _ = self._chartable()

        assert _stages(events) == ["router", "sql_gen", "sql_guard", "db_exec", "answer"]

    def test_a_result_with_nothing_to_plot_emits_no_chart(self):
        model = FakeToolModel(
            responses=[_tool_call("select vehicleno from vehicles"), AIMessage(content="Two.")]
        )
        events, outcome = _run(model, FakeConnector())

        assert "chart" not in [e["type"] for e in events]
        assert outcome.chart is None

    def test_a_refused_query_emits_no_chart(self):
        model = FakeToolModel(
            responses=[_tool_call("delete from vehicles"), AIMessage(content="No.")]
        )
        events, _ = _run(model, FakeConnector())

        assert "chart" not in [e["type"] for e in events]

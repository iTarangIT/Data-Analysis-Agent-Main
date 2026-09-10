from unittest.mock import patch

import pytest

from app.agent.nodes.answer import answer_node
from app.agent.nodes.db_exec import make_db_exec_node
from app.agent.nodes.router import RouteDecision, router_node
from app.agent.nodes.sql_gen import make_sql_gen_node
from app.agent.tools import make_query_tool

SCHEMA = {
    "tables": [
        {"name": "dealers", "columns": [{"name": "id", "type": "INTEGER"},
                                        {"name": "n", "type": "TEXT"}], "sample": [["1", "a"]]}
    ]
}


class FakeLLM:
    """Stands in for ChatOpenAI. Unit tests never reach the network."""

    def __init__(self, result):
        self.result = result
        self.seen: list = []
        self.bound_tools: list = []
        self.tool_choice = None

    def with_structured_output(self, _schema):
        return self

    def bind_tools(self, tools, tool_choice=None):
        self.bound_tools = tools
        self.tool_choice = tool_choice
        return self

    def invoke(self, msgs):
        self.seen = msgs
        return self.result


class ToolCallReply:
    """An AIMessage carrying tool calls, which is what bind_tools produces."""

    def __init__(self, *calls):
        self.tool_calls = [{"name": "query_database", "args": a, "id": f"c{i}"}
                           for i, a in enumerate(calls)]


class TestRouter:
    @pytest.mark.parametrize("tool", ["sql", "web", "clarify"])
    def test_returns_the_chosen_tool(self, tool):
        fake = FakeLLM(RouteDecision(tool=tool, reason="because"))
        with patch("app.agent.nodes.router.get_llm", return_value=fake):
            assert router_node({"question": "how many dealers", "schema": SCHEMA}) == {"tool": tool}

    def test_sends_the_table_summary_to_the_model(self):
        fake = FakeLLM(RouteDecision(tool="sql", reason="r"))
        with patch("app.agent.nodes.router.get_llm", return_value=fake):
            router_node({"question": "q", "schema": SCHEMA})
        assert "dealers(id, n)" in fake.seen[1].content


class TestSqlGen:
    @pytest.fixture
    def tool(self):
        return make_query_tool(FakeConnector(["n"], []), SCHEMA)

    def test_the_model_is_given_the_tool_and_told_to_call_it(self, tool):
        fake = FakeLLM(ToolCallReply({"sql": "SELECT 1"}))
        with patch("app.agent.nodes.sql_gen.get_llm", return_value=fake):
            make_sql_gen_node(tool)({"question": "q", "schema": SCHEMA})
        assert fake.bound_tools == [tool]
        assert fake.tool_choice == "query_database"

    def test_the_sql_comes_from_the_tool_call_arguments(self, tool):
        fake = FakeLLM(ToolCallReply({"sql": "  SELECT 1  "}))
        with patch("app.agent.nodes.sql_gen.get_llm", return_value=fake):
            out = make_sql_gen_node(tool)({"question": "q", "schema": SCHEMA, "guard_error": "old"})
        assert out == {"sql": "SELECT 1", "guard_error": None}

    def test_a_reply_with_no_tool_call_is_a_retry_not_a_crash(self, tool):
        fake = FakeLLM(ToolCallReply())
        with patch("app.agent.nodes.sql_gen.get_llm", return_value=fake):
            out = make_sql_gen_node(tool)({"question": "q", "schema": SCHEMA, "retries": 1})
        assert out["retries"] == 2 and "query_database" in out["guard_error"]
        assert "sql" not in out

    def test_the_rejection_reason_is_fed_back_on_a_retry(self, tool):
        fake = FakeLLM(ToolCallReply({"sql": "SELECT 2"}))
        with patch("app.agent.nodes.sql_gen.get_llm", return_value=fake):
            make_sql_gen_node(tool)(
                {"question": "q", "schema": SCHEMA, "sql": "SELECT bad",
                 "guard_error": "tables not allowed: ['secrets']"}
            )
        hint = fake.seen[-1].content
        assert "secrets" in hint and "SELECT bad" in hint

    def test_no_retry_hint_on_the_first_attempt(self, tool):
        fake = FakeLLM(ToolCallReply({"sql": "SELECT 1"}))
        with patch("app.agent.nodes.sql_gen.get_llm", return_value=fake):
            make_sql_gen_node(tool)({"question": "q", "schema": SCHEMA})
        assert len(fake.seen) == 2


class FakeConnector:
    kind = "postgres"

    def __init__(self, cols, rows, error=None):
        self.cols, self.rows, self.error = cols, rows, error
        self.asked_for = None

    def run_select(self, sql, max_rows):
        self.asked_for = max_rows
        if self.error:
            raise self.error
        return self.cols, self.rows[:max_rows]

    def describe_schema(self):
        return SCHEMA

    def test(self):
        return True


class TestDbExec:
    def _node(self, connector):
        return make_db_exec_node(make_query_tool(connector, SCHEMA))

    def test_returns_columns_and_rows_through_the_tool(self):
        out = self._node(FakeConnector(["n"], [("a",), ("b",)]))({"sql": "SELECT n FROM dealers"})
        assert out["columns"] == ["n"]
        assert out["rows"] == [["a"], ["b"]]
        assert out["truncated"] is False and out["guard_error"] is None

    def test_flags_truncation_without_returning_the_extra_row(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "max_rows", 2, raising=False)
        conn = FakeConnector(["n"], [("a",), ("b",), ("c",)])
        out = self._node(conn)({"sql": "SELECT n FROM dealers"})
        assert conn.asked_for == 3, "must request one row beyond the cap to detect truncation"
        assert out["rows"] == [["a"], ["b"]] and out["truncated"] is True

    def test_a_database_error_becomes_a_retry_hint(self):
        conn = FakeConnector([], [], error=RuntimeError("column x not found"))
        out = self._node(conn)({"sql": "SELECT x FROM dealers", "retries": 1})
        assert out["retries"] == 2 and "column x not found" in out["guard_error"]

    def test_the_guard_still_refuses_a_write_even_here(self):
        conn = FakeConnector(["n"], [("a",)])
        out = self._node(conn)({"sql": "DELETE FROM dealers", "retries": 0})
        assert out["retries"] == 1 and "DELETE" in out["guard_error"]
        assert conn.asked_for is None


class TestAnswer:
    def test_returns_the_models_prose(self):
        class Resp:
            content = "Three dealers."

        with patch("app.agent.nodes.answer.get_llm", return_value=FakeLLM(Resp())):
            out = answer_node({"question": "q", "sql": "SELECT 1", "columns": ["n"], "rows": [[3]]})
        assert out == {"answer": "Three dealers."}

    def test_truncates_the_row_preview_sent_to_the_model(self):
        class Resp:
            content = "ok"

        fake = FakeLLM(Resp())
        with patch("app.agent.nodes.answer.get_llm", return_value=fake):
            answer_node(
                {"question": "q", "sql": "s", "columns": ["n"], "rows": [[i] for i in range(200)]}
            )
        assert '"rows": [[0]' in fake.seen[1].content
        assert "[199]" not in fake.seen[1].content

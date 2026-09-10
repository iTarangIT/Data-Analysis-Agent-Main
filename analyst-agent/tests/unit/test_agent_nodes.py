from unittest.mock import patch

import pytest

from app.agent.nodes.answer import answer_node
from app.agent.nodes.db_exec import make_db_exec_node
from app.agent.nodes.router import RouteDecision, router_node
from app.agent.nodes.sql_gen import SqlDraft, sql_gen_node

SCHEMA = {
    "tables": [
        {"name": "dealers", "columns": [{"name": "id", "type": "INTEGER"}], "sample": [["1"]]}
    ]
}


class FakeLLM:
    """Stands in for ChatOpenAI. Unit tests never reach the network."""

    def __init__(self, result):
        self.result = result
        self.seen: list = []

    def with_structured_output(self, _schema):
        return self

    def invoke(self, msgs):
        self.seen = msgs
        return self.result


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
        assert "dealers(id)" in fake.seen[1].content


class TestSqlGen:
    def test_returns_the_drafted_sql_and_clears_any_previous_error(self):
        fake = FakeLLM(SqlDraft(sql="  SELECT 1  "))
        with patch("app.agent.nodes.sql_gen.get_llm", return_value=fake):
            out = sql_gen_node({"question": "q", "schema": SCHEMA, "guard_error": "old"})
        assert out == {"sql": "SELECT 1", "guard_error": None}

    def test_feeds_the_rejection_reason_back_on_a_retry(self):
        fake = FakeLLM(SqlDraft(sql="SELECT 2"))
        with patch("app.agent.nodes.sql_gen.get_llm", return_value=fake):
            sql_gen_node(
                {
                    "question": "q",
                    "schema": SCHEMA,
                    "sql": "SELECT bad",
                    "guard_error": "tables not allowed: ['secrets']",
                }
            )
        retry_hint = fake.seen[-1].content
        assert "secrets" in retry_hint and "SELECT bad" in retry_hint

    def test_sends_no_retry_hint_on_the_first_attempt(self):
        fake = FakeLLM(SqlDraft(sql="SELECT 1"))
        with patch("app.agent.nodes.sql_gen.get_llm", return_value=fake):
            sql_gen_node({"question": "q", "schema": SCHEMA})
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
    def test_returns_columns_and_rows(self):
        node = make_db_exec_node(FakeConnector(["n"], [("a",), ("b",)]))
        out = node({"sql": "SELECT n FROM dealers"})
        assert out["columns"] == ["n"]
        assert out["rows"] == [["a"], ["b"]]
        assert out["truncated"] is False and out["guard_error"] is None

    def test_flags_truncation_without_returning_the_extra_row(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "max_rows", 2, raising=False)
        conn = FakeConnector(["n"], [("a",), ("b",), ("c",)])
        out = make_db_exec_node(conn)({"sql": "SELECT n FROM dealers"})
        assert conn.asked_for == 3, "must request one row beyond the cap to detect truncation"
        assert out["rows"] == [["a"], ["b"]] and out["truncated"] is True

    def test_a_database_error_becomes_a_retry_hint(self):
        node = make_db_exec_node(FakeConnector([], [], error=RuntimeError("column x not found")))
        out = node({"sql": "SELECT x FROM dealers", "retries": 1})
        assert out["retries"] == 2 and "column x not found" in out["guard_error"]


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

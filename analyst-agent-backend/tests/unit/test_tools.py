import json

import pytest
from langchain_core.tools import BaseTool

from app.agent.tools import (
    PREVIEW_ROWS,
    WEB_TOOL_NAME,
    _table_list,
    make_query_tool,
    make_web_tool,
)

SCHEMA = {
    "tables": [
        {"name": "vehicles", "columns": [{"name": "vehicleno", "type": "TEXT"}], "sample": []},
        {"name": "alerts", "columns": [{"name": "severity", "type": "TEXT"}], "sample": []},
    ]
}


class FakeConnector:
    kind = "postgres"
    dialect = "postgres"

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
        _, artifact = call(tool, sql)
        assert artifact["error"]
        assert connector.executed == [], "the connector was called despite the guard refusing"

    def test_the_refusal_explains_itself_so_the_model_can_correct(self, tool):
        content, artifact = call(tool, "select * from secrets")
        assert "secrets" in artifact["error"]
        assert "secrets" in content, "the model must see why, to correct it"


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
        content, artifact = call(make_query_tool(wide, SCHEMA), "select vehicleno from vehicles")
        assert len(json.loads(content)["rows"]) == PREVIEW_ROWS
        assert len(artifact["rows"]) == PREVIEW_ROWS + 25, "the caller still gets every row"

    def test_a_database_failure_comes_back_as_an_error_not_an_exception(self):
        class Broken(FakeConnector):
            def run_select(self, sql, max_rows):
                raise RuntimeError("column does not exist")

        _, artifact = call(make_query_tool(Broken(), SCHEMA), "select vehicleno from vehicles")
        assert "column does not exist" in artifact["error"]

    def test_truncation_is_reported(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "max_rows", 1, raising=False)
        conn = FakeConnector(rows=(("a",), ("b",), ("c",)))
        _, artifact = call(make_query_tool(conn, SCHEMA), "select vehicleno from vehicles")
        assert artifact["truncated"] is True and artifact["rows"] == [["a"]]


class FakeDashboard:
    kind = "web"

    def __init__(self, rows=(("KA01", 82), ("KA02", 61))):
        self.rows = [tuple(r) for r in rows]
        self.calls = 0

    def fetch_rows(self, max_rows):
        self.calls += 1
        return ["vehicleno", "soc"], self.rows[:max_rows]

    def describe_schema(self):
        return WEB_SCHEMA


WEB_SCHEMA = {
    "tables": [
        {
            "name": "dashboard",
            "columns": [{"name": "vehicleno", "type": "str"}, {"name": "soc", "type": "int"}],
            "sample": [],
        }
    ]
}


class TestWebTool:
    def test_it_takes_no_arguments(self):
        tool = make_web_tool(FakeDashboard(), WEB_SCHEMA)

        assert tool.name == WEB_TOOL_NAME
        assert tool.args == {}, "a dashboard has one payload and no query language"

    def test_the_description_names_the_columns(self):
        tool = make_web_tool(FakeDashboard(), WEB_SCHEMA)

        assert "vehicleno" in tool.description and "dashboard" in tool.description

    def test_the_artifact_carries_no_sql(self):
        _, artifact = call(make_web_tool(FakeDashboard(), WEB_SCHEMA))

        assert "sql" not in artifact, "a web run must never report executed SQL"
        assert artifact["columns"] == ["vehicleno", "soc"]
        assert artifact["rows"] == [["KA01", 82], ["KA02", 61]]
        assert artifact["truncated"] is False

    def test_a_browser_failure_comes_back_as_an_error_not_an_exception(self):
        class Broken(FakeDashboard):
            def fetch_rows(self, max_rows):
                raise RuntimeError("login timed out")

        content, artifact = call(make_web_tool(Broken(), WEB_SCHEMA))

        assert "login timed out" in artifact["error"]
        assert "Could not read the dashboard" in content

    def test_the_model_sees_a_preview_while_the_caller_keeps_every_row(self):
        conn = FakeDashboard(rows=[(f"KA{i:04d}", i) for i in range(PREVIEW_ROWS + 25)])

        content, artifact = call(make_web_tool(conn, WEB_SCHEMA))

        assert len(json.loads(content)["rows"]) == PREVIEW_ROWS
        assert len(artifact["rows"]) == PREVIEW_ROWS + 25

    def test_truncation_is_reported(self, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "max_rows", 1, raising=False)
        _, artifact = call(make_web_tool(FakeDashboard(), WEB_SCHEMA))

        assert artifact["truncated"] is True
        assert len(artifact["rows"]) == 1


class TestTableAnnotations:
    """What the model is told each table holds, before it writes a query.

    Without this the model cannot tell an empty table from a filter that matched nothing, and
    answers both with a shrug. The wording is load-bearing: it has to be exact about
    emptiness and vague about size.
    """

    def _rendered(self, stats):
        schema = {
            "tables": [
                {"name": "trips", "columns": [{"name": "id", "type": "BIGINT"}], "stats": stats}
            ]
        }
        return _table_list(schema)

    def test_an_empty_table_says_so_in_words_the_model_cannot_miss(self):
        assert "EMPTY, holds no rows at all" in self._rendered({"rows": "empty"})

    def test_a_table_proven_to_hold_rows_is_not_called_empty(self):
        # `reltuples` is -1 until a table is analysed, and 0 for one analysed while empty and
        # bulk-loaded since. Neither proves emptiness, so neither may be rendered as it.
        rendered = self._rendered({"rows": "nonempty"})

        assert "EMPTY" not in rendered
        assert "has rows" in rendered

    def test_a_size_is_a_bucket_rather_than_a_count(self):
        rendered = self._rendered({"rows": "millions", "rows_approx": 46_000_000})

        assert "about 46,000,000 rows" in rendered

    def test_a_partial_estimate_says_it_is_a_floor(self):
        rendered = self._rendered(
            {"rows": "millions", "rows_approx": 46_000_000, "rows_at_least": True}
        )

        assert "at least about 46,000,000 rows" in rendered

    def test_stale_data_is_reported_as_where_the_rows_sit(self):
        # Not "data up to X": a partition bound is the edge of the partition, not the newest
        # row, and the description should not claim more than was measured.
        rendered = self._rendered({"rows": "millions", "covered_to": "2026-07-06"})

        assert "newest data sits in a partition ending 2026-07-06" in rendered

    def test_a_schema_cached_before_statistics_existed_still_renders(self):
        # The cache has a six hour life, so a deployment serves pre-change entries for a while.
        schema = {"tables": [{"name": "old", "columns": [{"name": "id", "type": "INTEGER"}]}]}

        assert _table_list(schema) == "TABLE old (id INTEGER)"

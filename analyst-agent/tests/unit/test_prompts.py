"""The system prompt is assembled from a shared frame and one capability block.

A connection has exactly one kind, so a run gets exactly one block. Telling a dashboard tenant
how to write SQL would only invite the model to claim it had queried a database.
"""

from datetime import date

from app.agent.prompts import AGENT_SYSTEM, SQL_CAPABILITY, WEB_CAPABILITY
from app.agent.tools import TOOL_NAME, WEB_TOOL_NAME, tools_for


def _compose(capability: str) -> str:
    return AGENT_SYSTEM.format(today=date.today().isoformat(), capability=capability)


class TestComposition:
    def test_the_sql_prompt_explains_sql_and_not_the_dashboard(self):
        prompt = _compose(SQL_CAPABILITY)

        assert "Writing SQL:" in prompt
        assert "dashboard" not in prompt.lower()

    def test_the_web_prompt_explains_the_dashboard_and_not_sql(self):
        prompt = _compose(WEB_CAPABILITY)

        assert "dashboard" in prompt.lower()
        assert "Writing SQL:" not in prompt

    def test_the_web_prompt_forbids_claiming_a_database_was_queried(self):
        assert "Never claim to have queried one." in WEB_CAPABILITY

    def test_the_web_prompt_bounds_retries_because_each_drives_a_browser(self):
        assert "more than twice" in WEB_CAPABILITY

    def test_both_prompts_carry_the_date_and_the_answering_rules(self):
        for prompt in (_compose(SQL_CAPABILITY), _compose(WEB_CAPABILITY)):
            assert date.today().isoformat() in prompt
            assert "Answering:" in prompt


class TestToolSelection:
    class _Source:
        def __init__(self, kind):
            self.kind = kind
            self.dialect = "postgres"

        def describe_schema(self):
            return {"tables": []}

    def test_a_web_connection_gets_only_the_dashboard_tool(self):
        tools = tools_for(self._Source("web"), {"tables": []})

        assert [t.name for t in tools] == [WEB_TOOL_NAME]

    def test_a_postgres_connection_gets_only_the_query_tool(self):
        tools = tools_for(self._Source("postgres"), {"tables": []})

        assert [t.name for t in tools] == [TOOL_NAME]

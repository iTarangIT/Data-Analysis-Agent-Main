"""The system prompt is assembled from a shared frame and one capability block.

A connection has exactly one kind, so a run gets exactly one block. Telling a dashboard tenant
how to write SQL would only invite the model to claim it had queried a database.
"""

from datetime import date

from app.agent.prompts import (
    AGENT_SYSTEM,
    FALLBACK_CAPABILITY,
    SQL_CAPABILITY,
    WEB_CAPABILITY,
)
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


class TestMissingData:
    """The answering rules that turn "no data found" into a useful answer.

    These assert on wording rather than behaviour, which only the evals can measure. They
    exist so a later edit cannot quietly drop a rule the policy depends on.
    """

    def test_every_figure_must_come_from_a_returned_row(self):
        assert "must come from a row a tool returned" in AGENT_SYSTEM

    def test_an_empty_result_has_to_be_explained_rather_than_reported(self):
        assert "work out why before you answer" in AGENT_SYSTEM

    def test_a_derived_answer_must_be_called_an_estimate(self):
        assert "say it is an estimate" in AGENT_SYSTEM

    def test_the_answer_stays_prose_because_the_client_renders_one_paragraph(self):
        assert "no headings and no bullet lists" in AGENT_SYSTEM

    def test_a_vague_question_is_answered_with_the_reading_stated(self):
        assert "say which reading you took" in AGENT_SYSTEM

    def test_the_sql_prompt_no_longer_licenses_answering_from_general_knowledge(self):
        # This line used to read "answer in one sentence without calling a tool", which was
        # the one place in the service that invited an answer from outside the customer's data.
        assert "Do not\n  answer it from your own knowledge" in SQL_CAPABILITY

    def test_the_sql_prompt_points_at_the_table_annotations(self):
        assert "Querying one\n  marked EMPTY wastes a turn" in SQL_CAPABILITY

    def test_the_web_prompt_refuses_to_guess_at_an_empty_dashboard(self):
        assert "Do not guess at what" in WEB_CAPABILITY


class TestFallbackPrompt:
    def _fallback(self):
        return FALLBACK_CAPABILITY.format(sql=SQL_CAPABILITY)

    def test_it_carries_the_sql_rules_rather_than_restating_them(self):
        assert "Writing SQL:" in self._fallback()

    def test_it_tells_the_answer_to_admit_the_live_reading_was_unavailable(self):
        assert "the live reading was unavailable" in self._fallback()

    def test_it_forbids_retrying_the_dashboard(self):
        assert "Do not call the dashboard tool again" in self._fallback()

    def test_it_is_never_part_of_an_ordinary_sql_prompt(self):
        """The invariant `app/agent/router.py` is built on.

        A run bound to the database must not learn that a dashboard exists, or it will offer
        to consult one it has no tool for. The fallback text is only ever composed once the
        dashboard has actually been tried and failed.
        """
        assert "dashboard" not in _compose(SQL_CAPABILITY).lower()

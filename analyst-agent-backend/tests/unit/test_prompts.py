"""The system prompt is a shared frame around the SQL capability block."""

from datetime import date

from app.agent.prompts import (
    AGENT_SYSTEM,
    FORECAST_CAPABILITY,
    FORECAST_OFF,
    SQL_CAPABILITY,
    capability,
)


def _compose() -> str:
    return AGENT_SYSTEM.format(today=date.today().isoformat(), capability=SQL_CAPABILITY)


class TestComposition:
    def test_the_prompt_carries_the_date_the_answering_rules_and_the_sql_rules(self):
        prompt = _compose()

        assert date.today().isoformat() in prompt
        assert "Answering:" in prompt
        assert "Writing SQL:" in prompt


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


class TestForecastingBlock:
    def test_the_sql_rules_come_first_either_way(self):
        assert capability(True).startswith(SQL_CAPABILITY)
        assert capability(False).startswith(SQL_CAPABILITY)

    def test_with_a_model_loaded_the_forecast_tool_is_explained(self):
        assert FORECAST_CAPABILITY in capability(True)
        assert FORECAST_OFF not in capability(True)

    def test_without_one_forecasting_is_declared_unavailable(self):
        assert FORECAST_OFF in capability(False)
        assert "do not work out a projection yourself" in FORECAST_OFF

    def test_forecast_figures_are_tool_output_but_never_hand_extrapolated(self):
        # AGENT_SYSTEM allows only figures a tool returned; a forecast's points are exactly that.
        assert "figures a tool returned" in FORECAST_CAPABILITY
        assert "Never extrapolate a figure yourself" in FORECAST_CAPABILITY

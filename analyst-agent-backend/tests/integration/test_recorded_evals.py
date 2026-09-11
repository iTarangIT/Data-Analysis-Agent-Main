"""The record/replay harness, proved end to end without spending model quota.

Recording normally wraps the real Gemini client. Here it wraps a scripted model, so the round
trip exercises the cassette format, the fingerprint and the replay path exactly as a real
recording would, at no cost.
"""

import json
import sys
from pathlib import Path

import pytest
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).parents[2] / "evals"))

import recorded

pytestmark = pytest.mark.integration


class ScriptedModel(FakeMessagesListChatModel):
    """Stands in for the real client that RecordingChatModel would otherwise wrap."""

    def bind_tools(self, tools, **kwargs):
        return self


def _script() -> ScriptedModel:
    return ScriptedModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "query_database",
                        "args": {"sql": "select count(*) as n from dealers"},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(content="There are three dealers."),
        ]
    )


@pytest.fixture
def connection_id(client, token, demo_dsn, clean_app_db) -> str:
    r = client.post(
        "/connections",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "demo", "kind": "postgres", "secret": {"dsn": demo_dsn}},
    )
    assert r.status_code == 201
    return r.json()["id"]


def _capture(client, token, connection_id, question, thread_id) -> recorded.RecordingChatModel:
    from unittest.mock import patch

    model = recorded.RecordingChatModel(inner=_script())
    with patch("app.agent.graph.get_llm", return_value=model):
        recorded._ask(client, token, connection_id, question, thread_id)
    return model


class TestRoundTrip:
    def test_a_recording_replays_to_the_same_answer(self, client, token, connection_id):
        from unittest.mock import patch

        question = "How many dealers do we have?"
        model = _capture(client, token, connection_id, question, "rec-1")
        assert len(model.turns) == 2, "one tool call and one answer"

        replayed = recorded.CassetteChatModel(turns=model.turns, tools_sha=model.tools_sha)
        with patch("app.agent.graph.get_llm", return_value=replayed):
            body = recorded._ask(client, token, connection_id, question, "rep-1")

        result = recorded._parse_sse(body)
        assert result["error"] is None
        assert result["rows"] == [[3]]
        assert result["answer"] == "There are three dealers."
        assert replayed.drift == [], "the replayed agent sent exactly what was recorded"

    def test_a_cassette_survives_json(self, client, token, connection_id):
        model = _capture(client, token, connection_id, "How many dealers do we have?", "rec-2")
        turns = json.loads(json.dumps(model.turns))

        message = AIMessage.model_validate(turns[0]["message"])
        assert message.tool_calls[0]["name"] == "query_database"
        assert message.tool_calls[0]["id"] == "c1", "tool call ids must survive, replay reuses them"


class TestDrift:
    def test_a_different_question_is_reported_as_drift(self, client, token, connection_id):
        from unittest.mock import patch

        model = _capture(client, token, connection_id, "How many dealers do we have?", "rec-3")
        replayed = recorded.CassetteChatModel(turns=model.turns)
        with patch("app.agent.graph.get_llm", return_value=replayed):
            recorded._ask(client, token, connection_id, "Something else entirely?", "rep-3")

        assert replayed.drift, "replaying under a different question must not score silently"

    def test_a_changed_tool_description_is_reported_as_drift(self, client, token, connection_id):
        from unittest.mock import patch

        model = _capture(client, token, connection_id, "How many dealers do we have?", "rec-4")
        replayed = recorded.CassetteChatModel(turns=model.turns, tools_sha="not-what-was-recorded")
        with patch("app.agent.graph.get_llm", return_value=replayed):
            recorded._ask(client, token, connection_id, "How many dealers do we have?", "rep-4")

        assert "tool descriptions" in replayed.drift


class TestPromptBinding:
    def test_the_cassette_name_changes_when_a_prompt_changes(self, monkeypatch):
        from app.agent import prompts

        before = recorded.cassette_path(Path("golden_sql.yaml")).name
        monkeypatch.setattr(prompts, "AGENT_SYSTEM", prompts.AGENT_SYSTEM + " Be terse.")
        after = recorded.cassette_path(Path("golden_sql.yaml")).name

        assert before != after, "an edited prompt must make the old recording unfindable"

    def test_replay_sees_the_day_it_recorded(self):
        from app.agent import graph

        with recorded.frozen_today("2026-01-31"):
            assert graph.date.today().isoformat() == "2026-01-31"

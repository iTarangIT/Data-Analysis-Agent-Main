"""End-to-end SSE. Needs the three local databases and a working OPENROUTER_API_KEY."""

import json
import os

import pytest

pytestmark = pytest.mark.integration

needs_llm = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GEMINI_API_KEY") == "test",
    reason="needs a real GEMINI_API_KEY",
)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events, name = [], None
    for line in text.splitlines():
        if line.startswith("event:"):
            name = line.removeprefix("event:").strip()
        elif line.startswith("data:") and name:
            events.append((name, json.loads(line.removeprefix("data:").strip())))
    return events


@pytest.fixture
def connection_id(client, token, demo_dsn, clean_app_db) -> str:
    r = client.post(
        "/connections",
        headers=_auth(token),
        json={"name": "demo", "kind": "postgres", "secret": {"dsn": demo_dsn}},
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_an_unknown_connection_is_a_404_not_a_stream(client, token, clean_app_db):
    r = client.post(
        "/runs",
        headers=_auth(token),
        json={"connection_id": "no-such-id", "thread_id": "t1", "question": "how many dealers"},
    )
    assert r.status_code == 404


def test_another_tenant_cannot_run_against_this_connection(client, other_token, connection_id):
    r = client.post(
        "/runs",
        headers=_auth(other_token),
        json={"connection_id": connection_id, "thread_id": "t1", "question": "how many dealers"},
    )
    assert r.status_code == 404


@needs_llm
def test_streams_the_full_sql_path(client, token, connection_id):
    r = client.post(
        "/runs",
        headers=_auth(token),
        json={
            "connection_id": connection_id,
            "thread_id": "t1",
            "question": "How many dealers do we have?",
        },
    )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    names = [n for n, _ in events]
    payloads = dict(events)

    assert "error" not in names, payloads.get("error")
    assert names[-1] == "done"
    assert {"status", "sql", "rows", "token"} <= set(names)
    assert payloads["sql"]["sql"].upper().startswith("SELECT")
    assert payloads["rows"]["rows"] == [[3]]


@needs_llm
def test_the_run_is_recorded_with_usage(client, token, connection_id, clean_app_db):
    client.post(
        "/runs",
        headers=_auth(token),
        json={
            "connection_id": connection_id,
            "thread_id": "t1",
            "question": "How many dealers do we have?",
        },
    )
    from app.db.models import Run

    run = clean_app_db.query(Run).order_by(Run.created_at.desc()).first()
    assert run.status == "done" and run.tool == "sql"
    assert run.prompt_tokens > 0 and run.rows_returned == 1


class TestFullStackWithAScriptedModel:
    """Exercises auth, prepare_run, the agent, the tool, the guard, the demo database, the SSE
    encoding and the Run row, without needing a model key."""

    @pytest.fixture
    def scripted(self):
        from langchain_core.language_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage

        class FakeToolModel(FakeMessagesListChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        return FakeToolModel(
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

    def test_streams_the_whole_contract_and_records_the_run(
        self, client, token, connection_id, clean_app_db, scripted
    ):
        from unittest.mock import patch

        with patch("app.agent.graph.get_llm", return_value=scripted):
            r = client.post(
                "/runs",
                headers=_auth(token),
                json={
                    "connection_id": connection_id,
                    "thread_id": "scripted-1",
                    "question": "How many dealers do we have?",
                },
            )
        assert r.status_code == 200
        events = _parse_sse(r.text)
        names = [n for n, _ in events]
        payload = dict(events)

        assert "error" not in names, payload.get("error")
        assert names[-1] == "done"
        assert [d["stage"] for n, d in events if n == "status"] == [
            "router",
            "sql_gen",
            "sql_guard",
            "db_exec",
            "answer",
        ]
        assert payload["sql"]["sql"].upper().startswith("SELECT")
        assert payload["rows"]["rows"] == [[3]]
        assert payload["token"]["text"] == "There are three dealers."

        from app.db.models import Run

        run = clean_app_db.query(Run).order_by(Run.created_at.desc()).first()
        assert run.status == "done" and run.tool == "sql" and run.rows_returned == 1

    def test_a_write_is_refused_by_the_guard_inside_the_tool(
        self, client, token, connection_id, clean_app_db
    ):
        from unittest.mock import patch

        from langchain_core.language_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage

        class FakeToolModel(FakeMessagesListChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        model = FakeToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "query_database",
                            "args": {"sql": "delete from dealers"},
                            "id": "c1",
                        }
                    ],
                ),
                AIMessage(content="I cannot modify your data."),
            ]
        )
        with patch("app.agent.graph.get_llm", return_value=model):
            r = client.post(
                "/runs",
                headers=_auth(token),
                json={
                    "connection_id": connection_id,
                    "thread_id": "scripted-2",
                    "question": "Delete the dealers please",
                },
            )
        events = _parse_sse(r.text)
        names = [n for n, _ in events]
        assert "sql" not in names, "a rejected statement was reported as executed SQL"
        assert "rows" not in names
        assert names[-1] == "done"


class TestNonJsonNativeColumnTypes:
    """A NUMERIC column arrives as a Decimal, which json.dumps cannot encode. Before this was
    handled the stream died mid-flight and the client saw a truncated body."""

    def test_a_numeric_column_streams_without_killing_the_response(
        self, client, token, connection_id, clean_app_db
    ):
        from unittest.mock import patch

        from langchain_core.language_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage

        class FakeToolModel(FakeMessagesListChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        model = FakeToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "query_database",
                            "args": {"sql": "select sum(price_inr) as total from batteries"},
                            "id": "c1",
                        }
                    ],
                ),
                AIMessage(content="Total revenue is 266300."),
            ]
        )
        with patch("app.agent.graph.get_llm", return_value=model):
            r = client.post(
                "/runs",
                headers=_auth(token),
                json={
                    "connection_id": connection_id,
                    "thread_id": "decimal-1",
                    "question": "What is the total battery revenue?",
                },
            )
        assert r.status_code == 200
        events = _parse_sse(r.text)
        names = [n for n, _ in events]
        assert names[-1] == "done", "the stream ended early, so a value failed to encode"

        rows = dict(events)["rows"]["rows"]
        assert rows == [["266300.00"]], "Decimal must survive as an exact string, not a float"

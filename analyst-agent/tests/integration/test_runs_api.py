"""End-to-end SSE. Needs the three local databases and a working OPENROUTER_API_KEY."""

import json
import os

import pytest

pytestmark = pytest.mark.integration

needs_llm = pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY", "").strip()
    or os.environ.get("OPENROUTER_API_KEY") == "test",
    reason="needs a real OPENROUTER_API_KEY",
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

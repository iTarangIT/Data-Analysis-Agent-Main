"""Phase 3's done-line: an Intellicar query works for two tenants with separate sessions.

Needs a real dashboard, so it skips unless the three INTELLICAR_* variables are exported.
pytest does not read `.env`; export them in the shell.

The model is scripted rather than real. The dashboard has to be live for this to prove
anything, but the model does not, and the free tier is 20 requests per day.
"""

import os
import shutil

import pytest
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from app.workers.web_session import session_path

pytestmark = pytest.mark.integration

needs_intellicar = pytest.mark.skipif(
    not os.environ.get("INTELLICAR_URL", "").strip(),
    reason="needs INTELLICAR_URL, INTELLICAR_ID and INTELLICAR_PASSWORD in the shell",
)


def _secret() -> dict:
    return {
        "url": os.environ["INTELLICAR_URL"],
        "username": os.environ["INTELLICAR_ID"],
        "password": os.environ["INTELLICAR_PASSWORD"],
        "data_url_match": os.environ.get("INTELLICAR_DATA_MATCH", "/api/"),
    }


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _scripted() -> ScriptedModel:
    return ScriptedModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "fetch_dashboard", "args": {}, "id": "w1"}]),
            AIMessage(content="Here is what the dashboard shows."),
        ]
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _connect(client, token: str) -> str:
    r = client.post(
        "/connections",
        headers=_auth(token),
        json={"name": "intellicar", "kind": "web", "secret": _secret()},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ask(client, token: str, connection_id: str, thread_id: str):
    from unittest.mock import patch

    from tests.integration.test_runs_api import _parse_sse

    with patch("app.agent.graph.get_llm", return_value=_scripted()):
        r = client.post(
            "/runs",
            headers=_auth(token),
            json={
                "connection_id": connection_id,
                "thread_id": thread_id,
                "question": "What does the dashboard show?",
            },
        )
    assert r.status_code == 200, r.text
    return _parse_sse(r.text)


@pytest.fixture
def clean_sessions():
    from app.config import get_settings

    root = get_settings().session_store_dir
    for tenant in ("t_test", "t_other"):
        shutil.rmtree(f"{root}/{tenant}", ignore_errors=True)
    yield


@needs_intellicar
class TestTwoTenants:
    def test_each_tenant_runs_against_their_own_session(
        self, client, token, other_token, clean_app_db, clean_sessions
    ):
        a_id = _connect(client, token)
        b_id = _connect(client, other_token)

        a = _ask(client, token, a_id, "web-a")
        b = _ask(client, other_token, b_id, "web-b")

        for events in (a, b):
            names = [n for n, _ in events]
            assert "error" not in names, dict(events).get("error")
            assert names[-1] == "done"
            assert [d["stage"] for n, d in events if n == "status"] == [
                "router",
                "web_tool",
                "answer",
            ]
            assert "sql" not in names, "a dashboard run must never report executed SQL"
            assert dict(events)["rows"]["columns"], "the dashboard returned no columns"

        a_file = session_path("t_test", a_id)
        b_file = session_path("t_other", b_id)
        assert a_file.exists() and b_file.exists()
        assert a_file.parent != b_file.parent, "two tenants shared a session directory"

    def test_a_second_run_reuses_the_saved_session(
        self, client, token, clean_app_db, clean_sessions
    ):
        conn_id = _connect(client, token)
        _ask(client, token, conn_id, "web-1")
        first = session_path("t_test", conn_id).stat().st_mtime_ns

        _ask(client, token, conn_id, "web-2")

        assert session_path("t_test", conn_id).stat().st_mtime_ns == first, (
            "the session was rewritten, so the second run logged in again"
        )

    def test_deleting_one_tenants_session_does_not_touch_the_other(
        self, client, token, other_token, clean_app_db, clean_sessions
    ):
        a_id = _connect(client, token)
        b_id = _connect(client, other_token)
        _ask(client, token, a_id, "web-a")
        _ask(client, other_token, b_id, "web-b")
        b_before = session_path("t_other", b_id).stat().st_mtime_ns

        session_path("t_test", a_id).unlink()
        _ask(client, token, a_id, "web-a2")

        assert session_path("t_test", a_id).exists(), "the tenant should have logged in again"
        assert session_path("t_other", b_id).stat().st_mtime_ns == b_before


@needs_intellicar
def test_a_wrong_password_is_a_400_not_a_broken_stream(client, token, clean_app_db, clean_sessions):
    """A web connection is not smoke-tested at creation, so this is where a bad credential
    surfaces. prepare_run runs before the stream opens, so it must still be a real status."""
    r = client.post(
        "/connections",
        headers=_auth(token),
        json={"name": "bad", "kind": "web", "secret": {**_secret(), "password": "not-the-one"}},
    )
    assert r.status_code == 201

    run = client.post(
        "/runs",
        headers=_auth(token),
        json={
            "connection_id": r.json()["id"],
            "thread_id": "bad-1",
            "question": "What does the dashboard show?",
        },
    )
    assert run.status_code == 400
    assert "not-the-one" not in run.text
    assert os.environ["INTELLICAR_PASSWORD"] not in run.text

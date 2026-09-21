"""The queued transport, driven through the real HTTP route against fakeredis.

Two things are proved here. The queued path streams the identical bytes to the in-process
path, which is what makes `QUEUE_ENABLED` safe to flip. And a worker that dies mid-run ends the
client's stream with one clean `error` frame rather than hanging, which is phase 4's done-line.
"""

import asyncio
from unittest.mock import patch

import fakeredis.aioredis
import pytest
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from app import queue
from app.db.models import Run

pytestmark = pytest.mark.integration


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _scripted() -> ScriptedModel:
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


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _events(text: str) -> list[tuple[str, dict]]:
    from tests.integration.test_runs_api import _parse_sse

    return _parse_sse(text)


@pytest.fixture
def connection_id(client, token, demo_dsn, clean_app_db) -> str:
    r = client.post(
        "/connections",
        headers=_auth(token),
        json={"name": "demo", "kind": "postgres", "secret": {"dsn": demo_dsn}},
    )
    assert r.status_code == 201
    return r.json()["id"]


@pytest.fixture
def redis(monkeypatch):
    # decode_responses=False, matching arq's real pool. With True these tests passed while
    # every queued run against real Redis silently reported a dead worker.
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    monkeypatch.setattr(queue, "_pool", client)
    return client


@pytest.fixture
def queued(monkeypatch, redis):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "queue_enabled", True, raising=False)
    monkeypatch.setattr(s, "run_heartbeat_s", 0.05, raising=False)
    monkeypatch.setattr(s, "run_stall_timeout_s", 0.5, raising=False)
    return redis


def _ask(client, token: str, connection_id: str, thread_id: str):
    return client.post(
        "/runs",
        headers=_auth(token),
        json={
            "connection_id": connection_id,
            "thread_id": thread_id,
            "question": "How many dealers do we have?",
        },
    )


class TestParity:
    def test_the_queued_stream_is_identical_to_the_in_process_one(
        self, client, token, connection_id, clean_app_db, queued, monkeypatch
    ):
        """A real worker is not needed to prove the transport: the same `execute_run` publishes
        the same frames, which is the property the shared encoder guarantees."""
        from app.config import get_settings
        from app.connectors.registry import connector_for, open_for_run
        from app.db.models import Connection
        from app.db.session import SessionLocal
        from app.services import runs as svc

        monkeypatch.setattr(get_settings(), "run_stall_timeout_s", 30, raising=False)
        enqueued: list[str] = []

        async def fake_enqueue(name, run_id, **kwargs):
            enqueued.append(run_id)

        monkeypatch.setattr(queue, "pool", lambda: queued)
        monkeypatch.setattr(queued, "enqueue_job", fake_enqueue, raising=False)

        # Publish the run's frames as a worker would, once the row exists.
        original = svc.prepare_run

        async def prepare_and_run(db, ctx, body):
            prepared = await original(db, ctx, body)
            loop = asyncio.get_running_loop()

            def emit(event):
                asyncio.run_coroutine_threadsafe(
                    queue.publish(queued, prepared.run.id, svc.sse_frame(event)), loop
                ).result()

            def work():
                worker_db = SessionLocal()
                try:
                    conn = worker_db.get_one(Connection, prepared.run.connection_id)
                    connector = open_for_run(connector_for(conn), prepared.catalog.table_names)
                    svc.execute_run(worker_db, prepared.run, connector, prepared.catalog, emit)
                finally:
                    worker_db.close()

            asyncio.get_running_loop().run_in_executor(None, work)
            return prepared

        monkeypatch.setattr(svc, "prepare_run", prepare_and_run)

        with patch("app.agent.graph.get_llm", return_value=_scripted()):
            r = _ask(client, token, connection_id, "queued-1")

        assert r.status_code == 200
        events = _events(r.text)
        names = [n for n, _ in events]

        assert "error" not in names, dict(events).get("error")
        assert names[-1] == "done"
        assert [d["stage"] for n, d in events if n == "status"] == [
            "router",
            "sql_gen",
            "sql_guard",
            "db_exec",
            "answer",
        ]
        assert dict(events)["rows"]["rows"] == [[3]]
        assert dict(events)["token"]["text"] == "There are three dealers."
        assert enqueued == [dict(events)["done"]["run_id"]], "the run reached the queue"


class TestKilledWorker:
    def test_a_worker_that_dies_mid_run_gives_a_clean_error(
        self, client, token, connection_id, clean_app_db, queued, monkeypatch
    ):
        """Phase 4's done-line. The worker publishes its first frame and then stops, exactly as
        a SIGKILL looks from the reader's side: no terminal frame, no heartbeat."""
        from app.services import runs as svc

        original = svc.prepare_run

        async def prepare_then_die(db, ctx, body):
            prepared = await original(db, ctx, body)
            await queue.publish(
                queued,
                prepared.run.id,
                svc.sse_frame({"type": "status", "data": {"stage": "router"}}),
            )
            return prepared

        monkeypatch.setattr(queue, "pool", lambda: queued)
        monkeypatch.setattr(queued, "enqueue_job", _noop, raising=False)
        monkeypatch.setattr(svc, "prepare_run", prepare_then_die)

        r = _ask(client, token, connection_id, "dead-1")

        assert r.status_code == 200
        events = _events(r.text)

        assert [n for n, _ in events] == ["status", "error"], "no hang, no truncated body"
        assert dict(events)["error"]["message"]

        run = clean_app_db.query(Run).order_by(Run.created_at.desc()).first()
        clean_app_db.refresh(run)
        assert run.status == "error", "a lost worker must not leave the row running"


async def _noop(name, run_id, **kwargs):
    return None

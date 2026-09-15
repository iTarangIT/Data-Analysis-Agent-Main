"""Choosing the tables the agent may use, end to end through the API and the demo database.

Each test runs as a tenant of its own and removes what it made. `clean_app_db` is deliberately
not used: it empties the whole App DB, which on a development machine is also the real account.
"""

import json
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

# In the demo fixture as seeded by every version of scripts/demo_customer.sql.
SEEDED = {"batteries", "dealers", "readings", "telemetry"}


def _headers(tenant_id: str) -> dict:
    from jose import jwt

    from app.config import get_settings

    token = jwt.encode(
        {"tenant_id": tenant_id, "sub": "u_tables"},
        get_settings().jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth():
    from app.db.session import SessionLocal

    tenant_id = f"t_tables_{uuid.uuid4().hex[:8]}"
    yield _headers(tenant_id)

    db = SessionLocal()
    try:
        owned = {"t": tenant_id}
        db.execute(
            text(
                "DELETE FROM connection_tables WHERE connection_id IN "
                "(SELECT id FROM connections WHERE tenant_id = :t)"
            ),
            owned,
        )
        db.execute(text("DELETE FROM runs WHERE tenant_id = :t"), owned)
        db.execute(text("DELETE FROM connections WHERE tenant_id = :t"), owned)
        db.execute(text("DELETE FROM tenants WHERE id = :t"), owned)
        db.commit()
    finally:
        db.close()


@pytest.fixture
def connection_id(client, auth, demo_dsn) -> str:
    r = client.post(
        "/connections",
        headers=auth,
        json={"name": "demo", "kind": "postgres", "secret": {"dsn": demo_dsn}},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _read(client, auth, connection_id) -> dict:
    r = client.get(f"/connections/{connection_id}/tables", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def _choose(client, auth, connection_id, names):
    return client.put(f"/connections/{connection_id}/tables", headers=auth, json={"tables": names})


def _by_name(body: dict) -> dict:
    return {t["name"]: t for t in body["tables"]}


def _selected(body: dict) -> set[str]:
    return {t["name"] for t in body["tables"] if t["selected"]}


def _joins(body: dict) -> set[tuple]:
    return {
        (
            r["from_table"],
            tuple(r["from_columns"]),
            r["to_table"],
            tuple(r["to_columns"]),
            r["origin"],
        )
        for r in body["relationships"]
    }


class TestANewConnection:
    def test_lists_every_table_and_chooses_them_all_when_they_fit_under_the_cap(
        self, client, auth, connection_id
    ):
        tables = _by_name(_read(client, auth, connection_id))

        assert set(tables) >= SEEDED
        assert all(t["selected"] for t in tables.values())
        assert tables["batteries"]["definition"]["primary_key"] == ["id"]

    def test_knows_how_its_tables_join_from_the_declared_keys(self, client, auth, connection_id):
        assert _joins(_read(client, auth, connection_id)) >= {
            ("batteries", ("dealer_id",), "dealers", ("id",), "declared"),
            ("telemetry", ("battery_id",), "batteries", ("id",), "declared"),
        }

    def test_the_connection_list_counts_its_tables(self, client, auth, connection_id):
        total = len(_read(client, auth, connection_id)["tables"])

        (listed,) = client.get("/connections", headers=auth).json()

        assert (listed["selected_tables"], listed["total_tables"]) == (total, total)


class TestChoosing:
    def test_structure_is_kept_only_for_the_tables_chosen(self, client, auth, connection_id):
        r = _choose(client, auth, connection_id, ["dealers", "batteries"])

        assert r.status_code == 200, r.text
        body = r.json()
        assert _selected(body) == {"dealers", "batteries"}
        telemetry = _by_name(body)["telemetry"]
        assert (telemetry["definition"], telemetry["stats"]) == (None, None)
        assert _joins(body) == {("batteries", ("dealer_id",), "dealers", ("id",), "declared")}

    def test_the_choice_is_what_a_later_read_returns(self, client, auth, connection_id):
        _choose(client, auth, connection_id, ["dealers"])

        assert _selected(_read(client, auth, connection_id)) == {"dealers"}

    def test_more_tables_than_the_cap_is_refused_and_changes_nothing(
        self, client, auth, connection_id, monkeypatch
    ):
        from app.config import get_settings

        before = _selected(_read(client, auth, connection_id))
        monkeypatch.setattr(get_settings(), "max_agent_tables", 1)

        r = _choose(client, auth, connection_id, ["dealers", "batteries"])

        assert r.status_code == 400
        assert "at most 1" in r.json()["error"]
        assert _selected(_read(client, auth, connection_id)) == before

    def test_a_table_the_source_does_not_have_is_refused_by_name(self, client, auth, connection_id):
        r = _choose(client, auth, connection_id, ["dealers", "invoices"])

        assert r.status_code == 400
        assert "invoices" in r.json()["error"]

    def test_another_tenant_can_neither_see_nor_change_the_choice(self, client, connection_id):
        other = _headers(f"t_tables_other_{uuid.uuid4().hex[:8]}")
        base = f"/connections/{connection_id}/tables"

        assert client.get(base, headers=other).status_code == 404
        assert client.put(base, headers=other, json={"tables": []}).status_code == 404
        assert client.post(f"{base}/refresh", headers=other).status_code == 404


class TestRefreshing:
    def test_a_new_table_arrives_unchosen_and_a_vanished_one_is_reported(
        self, client, auth, connection_id, monkeypatch
    ):
        from app.catalog.types import Column, TableDef

        before = set(_by_name(_read(client, auth, connection_id)))

        class Altered:
            """The demo source after someone dropped `telemetry` and created `invoices`."""

            def list_tables(self):
                return sorted((before - {"telemetry"}) | {"invoices"})

            def read_tables(self, names):
                return [
                    TableDef(name=n, columns=[Column(name="id", type="integer")]) for n in names
                ]

            def table_stats(self, names):
                return {}

        monkeypatch.setattr("app.services.tables.connector_for", lambda conn: Altered())

        r = client.post(f"/connections/{connection_id}/tables/refresh", headers=auth)

        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["added"], body["removed"]) == (["invoices"], ["telemetry"])
        tables = _by_name(body)
        assert "telemetry" not in tables
        assert tables["invoices"]["selected"] is False


class TestRuns:
    @staticmethod
    def _ask(client, auth, connection_id, sql):
        from langchain_core.language_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage

        class FakeToolModel(FakeMessagesListChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        model = FakeToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "query_database", "args": {"sql": sql}, "id": "c1"}],
                ),
                AIMessage(content="Done."),
            ]
        )
        with patch("app.agent.graph.get_llm", return_value=model):
            return client.post(
                "/runs",
                headers=auth,
                json={
                    "connection_id": connection_id,
                    "thread_id": f"tables-{uuid.uuid4().hex[:8]}",
                    "question": "How many are there?",
                },
            )

    @staticmethod
    def _events(response) -> list[tuple[str, dict]]:
        events, name = [], None
        for line in response.text.splitlines():
            if line.startswith("event:"):
                name = line.removeprefix("event:").strip()
            elif line.startswith("data:") and name:
                events.append((name, json.loads(line.removeprefix("data:").strip())))
        return events

    def test_a_connection_with_nothing_chosen_is_refused_before_the_stream_opens(
        self, client, auth, connection_id
    ):
        _choose(client, auth, connection_id, [])

        r = self._ask(client, auth, connection_id, "select count(*) from dealers")

        assert r.status_code == 400
        assert "choose" in r.json()["error"]

    def test_a_query_on_a_chosen_table_runs(self, client, auth, connection_id):
        _choose(client, auth, connection_id, ["dealers"])

        events = dict(
            self._events(
                self._ask(client, auth, connection_id, "select count(*) as n from dealers")
            )
        )

        assert events["rows"]["rows"] == [[3]]

    def test_a_query_on_a_table_that_was_not_chosen_never_reaches_the_database(
        self, client, auth, connection_id
    ):
        _choose(client, auth, connection_id, ["dealers"])

        r = self._ask(client, auth, connection_id, "select count(*) as n from batteries")

        names = [n for n, _ in self._events(r)]
        assert r.status_code == 200
        assert "sql" not in names and "rows" not in names


def test_deleting_a_connection_forgets_its_tables(client, auth, connection_id):
    from app.db.models import ConnectionTable
    from app.db.session import SessionLocal

    assert client.delete(f"/connections/{connection_id}", headers=auth).status_code == 204

    db = SessionLocal()
    try:
        assert db.query(ConnectionTable).filter_by(connection_id=connection_id).count() == 0
    finally:
        db.close()

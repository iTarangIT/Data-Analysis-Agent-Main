from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tests import supabase_tokens

pytestmark = pytest.mark.integration


def _account(client, email="owner@example.com"):
    """Sign in through Supabase and create an organisation, the way a new person does."""
    headers = {"Authorization": f"Bearer {supabase_tokens.mint(email=email)}"}
    r = client.post("/auth/provision", json={"tenant_name": "Acme"}, headers=headers)
    assert r.status_code == 201, r.text
    return {"user": r.json()}, headers


def _connection(client, headers, demo_dsn, name="demo"):
    r = client.post(
        "/connections",
        headers=headers,
        json={"name": name, "kind": "postgres", "secret": {"dsn": demo_dsn}},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed_runs(db, tenant_id, connection_id, specs):
    """Insert run rows directly. The agent is not what these tests are about, and driving a
    real model here would make them slow and non-deterministic."""
    from app.db.models import Run

    base = datetime.now(UTC) - timedelta(hours=1)
    made = []
    for i, spec in enumerate(specs):
        run = Run(
            tenant_id=tenant_id,
            connection_id=connection_id,
            thread_id=spec.get("thread_id", "t1"),
            question=spec.get("question", f"question {i}"),
            status=spec.get("status", "done"),
            tool=spec.get("tool", "sql"),
            sql=spec.get("sql", "SELECT 1"),
            answer=spec.get("answer", "Three dealers."),
            rows_returned=spec.get("rows_returned", 3),
            duration_ms=spec.get("duration_ms", 120),
            created_at=base + timedelta(minutes=i),
        )
        db.add(run)
        made.append(run)
    db.commit()
    for run in made:
        db.refresh(run)
    return made


class TestListRuns:
    def test_returns_the_tenants_runs_newest_first(self, client, clean_app_db, demo_dsn):
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        _seed_runs(
            clean_app_db,
            body["user"]["tenant_id"],
            conn,
            [{"question": "first"}, {"question": "second"}],
        )

        items = client.get("/runs", headers=headers).json()["items"]
        assert [i["question"] for i in items] == ["second", "first"]

    def test_carries_the_connection_name_without_a_query_per_row(
        self, client, clean_app_db, demo_dsn
    ):
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn, name="warehouse")
        _seed_runs(clean_app_db, body["user"]["tenant_id"], conn, [{}])

        assert (
            client.get("/runs", headers=headers).json()["items"][0]["connection_name"]
            == "warehouse"
        )

    def test_omits_the_heavy_text_columns(self, client, clean_app_db, demo_dsn):
        """The list is a navigation surface; sql and answer are unbounded text."""
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        _seed_runs(clean_app_db, body["user"]["tenant_id"], conn, [{}])

        item = client.get("/runs", headers=headers).json()["items"][0]
        assert "sql" not in item
        assert "answer" not in item
        assert item["has_sql"] is True
        assert item["has_answer"] is True

    def test_flags_a_run_that_produced_nothing(self, client, clean_app_db, demo_dsn):
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        _seed_runs(
            clean_app_db,
            body["user"]["tenant_id"],
            conn,
            [{"sql": None, "answer": None, "status": "error"}],
        )

        item = client.get("/runs", headers=headers).json()["items"][0]
        assert item["has_sql"] is False
        assert item["has_answer"] is False

    def test_filters_by_thread(self, client, clean_app_db, demo_dsn):
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        _seed_runs(
            clean_app_db,
            body["user"]["tenant_id"],
            conn,
            [{"thread_id": "a"}, {"thread_id": "b"}, {"thread_id": "a"}],
        )

        items = client.get("/runs?thread_id=a", headers=headers).json()["items"]
        assert len(items) == 2
        assert {i["thread_id"] for i in items} == {"a"}

    def test_filters_by_status(self, client, clean_app_db, demo_dsn):
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        _seed_runs(
            clean_app_db,
            body["user"]["tenant_id"],
            conn,
            [{"status": "done"}, {"status": "error"}],
        )

        items = client.get("/runs?status=error", headers=headers).json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "error"

    def test_pages_without_repeating_or_skipping_a_row(self, client, clean_app_db, demo_dsn):
        """Keyset paging, which is why the cursor exists rather than an offset."""
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        _seed_runs(
            clean_app_db,
            body["user"]["tenant_id"],
            conn,
            [{"question": f"q{i}"} for i in range(5)],
        )

        seen, cursor = [], None
        for _ in range(5):
            url = f"/runs?limit=2{f'&cursor={cursor}' if cursor else ''}"
            page = client.get(url, headers=headers).json()
            seen += [i["question"] for i in page["items"]]
            cursor = page["next_cursor"]
            if cursor is None:
                break

        assert seen == ["q4", "q3", "q2", "q1", "q0"]
        assert len(seen) == len(set(seen))

    def test_the_last_page_has_no_cursor(self, client, clean_app_db, demo_dsn):
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        _seed_runs(clean_app_db, body["user"]["tenant_id"], conn, [{}, {}])

        assert client.get("/runs?limit=50", headers=headers).json()["next_cursor"] is None

    def test_a_corrupt_cursor_is_a_clean_400(self, client, clean_app_db):
        _, headers = _account(client)
        r = client.get("/runs?cursor=not-base64!!", headers=headers)
        assert r.status_code == 400
        assert r.json() == {"error": "that page cursor is not valid"}

    def test_another_tenant_sees_nothing(self, client, clean_app_db, demo_dsn):
        a_body, a_headers = _account(client, "a@example.com")
        _, b_headers = _account(client, "b@example.com")
        conn = _connection(client, a_headers, demo_dsn)
        _seed_runs(clean_app_db, a_body["user"]["tenant_id"], conn, [{}, {}])

        assert client.get("/runs", headers=a_headers).json()["items"] != []
        assert client.get("/runs", headers=b_headers).json()["items"] == []

    def test_requires_a_token(self, client, clean_app_db):
        assert client.get("/runs").status_code == 401


class TestListThreads:
    def test_groups_runs_into_conversations(self, client, clean_app_db, demo_dsn):
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        _seed_runs(
            clean_app_db,
            body["user"]["tenant_id"],
            conn,
            [{"thread_id": "a"}, {"thread_id": "a"}, {"thread_id": "b"}],
        )

        threads = client.get("/runs/threads", headers=headers).json()
        by_id = {t["thread_id"]: t for t in threads}
        assert by_id["a"]["run_count"] == 2
        assert by_id["b"]["run_count"] == 1

    def test_the_title_is_the_first_question_asked(self, client, clean_app_db, demo_dsn):
        # Not the newest: a thread is named by what started it.
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        _seed_runs(
            clean_app_db,
            body["user"]["tenant_id"],
            conn,
            [
                {"thread_id": "a", "question": "how many dealers?"},
                {"thread_id": "a", "question": "and which sold most?"},
            ],
        )

        threads = client.get("/runs/threads", headers=headers).json()
        assert threads[0]["title"] == "how many dealers?"

    def test_a_long_title_is_truncated_server_side(self, client, clean_app_db, demo_dsn):
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        _seed_runs(clean_app_db, body["user"]["tenant_id"], conn, [{"question": "x" * 500}])

        assert len(client.get("/runs/threads", headers=headers).json()[0]["title"]) == 120

    def test_carries_the_newest_status(self, client, clean_app_db, demo_dsn):
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        _seed_runs(
            clean_app_db,
            body["user"]["tenant_id"],
            conn,
            [{"thread_id": "a", "status": "done"}, {"thread_id": "a", "status": "error"}],
        )

        assert client.get("/runs/threads", headers=headers).json()[0]["last_status"] == "error"

    def test_threads_is_not_matched_as_a_run_id(self, client, clean_app_db):
        """Route ordering: /runs/threads must be declared before /runs/{run_id}."""
        _, headers = _account(client)
        r = client.get("/runs/threads", headers=headers)
        assert r.status_code == 200
        assert r.json() == []

    def test_another_tenant_sees_no_threads(self, client, clean_app_db, demo_dsn):
        a_body, a_headers = _account(client, "a@example.com")
        _, b_headers = _account(client, "b@example.com")
        conn = _connection(client, a_headers, demo_dsn)
        _seed_runs(clean_app_db, a_body["user"]["tenant_id"], conn, [{}])

        assert client.get("/runs/threads", headers=b_headers).json() == []


class TestRunDetail:
    def test_returns_the_sql_and_the_answer(self, client, clean_app_db, demo_dsn):
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        run = _seed_runs(
            clean_app_db,
            body["user"]["tenant_id"],
            conn,
            [{"sql": "SELECT count(*) FROM dealers", "answer": "There are three dealers."}],
        )[0]

        detail = client.get(f"/runs/{run.id}", headers=headers).json()
        assert detail["sql"] == "SELECT count(*) FROM dealers"
        assert detail["answer"] == "There are three dealers."

    def test_carries_no_result_rows(self, client, clean_app_db, demo_dsn):
        """`runs` records how many rows came back, never what they were."""
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        run = _seed_runs(clean_app_db, body["user"]["tenant_id"], conn, [{}])[0]

        detail = client.get(f"/runs/{run.id}", headers=headers).json()
        assert "rows" not in detail
        assert detail["rows_returned"] == 3

    def test_an_older_run_reports_a_null_answer(self, client, clean_app_db, demo_dsn):
        # NULL means not recorded, which every run predating the column is.
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        run = _seed_runs(clean_app_db, body["user"]["tenant_id"], conn, [{"answer": None}])[0]

        assert client.get(f"/runs/{run.id}", headers=headers).json()["answer"] is None

    def test_another_tenants_run_is_a_404_not_a_403(self, client, clean_app_db, demo_dsn):
        # 403 would confirm the run exists.
        a_body, a_headers = _account(client, "a@example.com")
        _, b_headers = _account(client, "b@example.com")
        conn = _connection(client, a_headers, demo_dsn)
        run = _seed_runs(clean_app_db, a_body["user"]["tenant_id"], conn, [{}])[0]

        r = client.get(f"/runs/{run.id}", headers=b_headers)
        assert r.status_code == 404
        assert r.json() == {"error": "run not found"}


class TestDeleteConnection:
    def test_removes_it_from_the_list(self, client, clean_app_db, demo_dsn):
        _, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)

        assert client.delete(f"/connections/{conn}", headers=headers).status_code == 204
        assert client.get("/connections", headers=headers).json() == []

    def test_destroys_the_stored_credential(self, client, clean_app_db, demo_dsn):
        """Deleting a connection has to mean the customer's password is gone, not hidden."""
        from app.db.models import Connection

        _, headers = _account(client)
        conn_id = _connection(client, headers, demo_dsn)
        client.delete(f"/connections/{conn_id}", headers=headers)

        row = clean_app_db.scalar(select(Connection).where(Connection.id == conn_id))
        assert row is not None  # the row survives, so history can still name the source
        assert row.secret_enc == ""
        assert (row.relationships, row.catalog_refreshed_at) == (None, None)
        assert "postgresql" not in row.secret_enc

    def test_a_run_against_a_deleted_connection_is_a_404(self, client, clean_app_db, demo_dsn):
        _, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        client.delete(f"/connections/{conn}", headers=headers)

        r = client.post(
            "/runs",
            headers=headers,
            json={"connection_id": conn, "thread_id": "t1", "question": "how many?"},
        )
        assert r.status_code == 404
        assert r.json() == {"error": "connection not found"}

    def test_the_ledger_survives(self, client, clean_app_db, demo_dsn):
        """Cascading would delete billing history along with a tidied-up list."""
        body, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        _seed_runs(clean_app_db, body["user"]["tenant_id"], conn, [{}, {}])

        client.delete(f"/connections/{conn}", headers=headers)

        items = client.get("/runs", headers=headers).json()["items"]
        assert len(items) == 2
        # And the source is still nameable, which a hard delete would have lost.
        assert items[0]["connection_name"] == "demo"

    def test_deleting_twice_is_a_404(self, client, clean_app_db, demo_dsn):
        _, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        client.delete(f"/connections/{conn}", headers=headers)

        assert client.delete(f"/connections/{conn}", headers=headers).status_code == 404

    def test_another_tenant_cannot_delete_it(self, client, clean_app_db, demo_dsn):
        _, a_headers = _account(client, "a@example.com")
        _, b_headers = _account(client, "b@example.com")
        conn = _connection(client, a_headers, demo_dsn)

        assert client.delete(f"/connections/{conn}", headers=b_headers).status_code == 404
        # And A still has it.
        assert client.get("/connections", headers=a_headers).json() != []

    def test_requires_a_token(self, client, clean_app_db, demo_dsn):
        _, headers = _account(client)
        conn = _connection(client, headers, demo_dsn)
        assert client.delete(f"/connections/{conn}").status_code == 401

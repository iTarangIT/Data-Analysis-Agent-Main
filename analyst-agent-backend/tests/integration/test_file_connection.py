"""Upload a spreadsheet, then ask a question about it. Phase 5's done-line.

The model is scripted, so this costs no quota; what it proves is the upload route, the ingest,
the connector, the duckdb dialect through the guard, and the frozen SSE contract.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

pytestmark = pytest.mark.integration

CSV = (
    "order_date,region,product,units,revenue_inr\n"
    "2026-07-04,West,Cell,10,2500.50\n"
    "2026-07-11,East,Pack,4,1800.00\n"
    "2026-08-02,West,Cell,6,1500.25\n"
)
DEALERS = "dealer,region\nPune Motors,West\nNashik EV,East\n"
STOCK = "product,units\nCell,16\nPack,4\n"


class ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _script(sql: str, answer: str) -> ScriptedModel:
    return ScriptedModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "query_database", "args": {"sql": sql}, "id": "c1"}],
            ),
            AIMessage(content=answer),
        ]
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _parts(files: tuple[tuple[str, bytes], ...]) -> list:
    return [("files", (filename, body, "text/csv")) for filename, body in files]


def _upload(client, token: str, name: str, *files: tuple[str, bytes]):
    return client.post(
        "/connections/file", headers=_auth(token), data={"name": name}, files=_parts(files)
    )


def _add(client, token: str, connection_id: str, *files: tuple[str, bytes]):
    return client.post(
        f"/connections/{connection_id}/files", headers=_auth(token), files=_parts(files)
    )


def _tables(client, token: str, connection_id: str) -> dict[str, dict]:
    r = client.get(f"/connections/{connection_id}/tables", headers=_auth(token))
    return {t["name"]: t for t in r.json()["tables"]}


def _sources(db, connection_id: str) -> list[dict]:
    from app.db.models import Connection
    from app.security import vault

    db.expire_all()
    return vault.decrypt(db.get(Connection, connection_id).secret_enc)["sources"]


def _ask(client, token: str, connection_id: str, sql: str, thread_id: str):
    from tests.integration.test_runs_api import _parse_sse

    with patch("app.agent.graph.get_llm", return_value=_script(sql, "Here is what I found.")):
        r = client.post(
            "/runs",
            headers=_auth(token),
            json={
                "connection_id": connection_id,
                "thread_id": thread_id,
                "question": "What does the data say?",
            },
        )
    assert r.status_code == 200
    return _parse_sse(r.text)


@pytest.fixture
def uploads_dir(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "file_store_dir", str(tmp_path), raising=False)
    return tmp_path


@pytest.fixture
def connection_id(client, token, clean_app_db, uploads_dir) -> str:
    r = _upload(client, token, "Q3 sales", ("Q3 sales.csv", CSV.encode()))
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def connection_dir(uploads_dir, connection_id) -> Path:
    return uploads_dir / "t_test" / connection_id


class TestUpload:
    def test_it_registers_a_file_connection(self, client, token, connection_id):
        listed = client.get("/connections", headers=_auth(token)).json()

        assert [c["kind"] for c in listed] == ["file"]
        assert listed[0]["name"] == "Q3 sales"
        assert listed[0]["file_count"] == 1

    def test_the_stored_paths_are_under_this_tenants_directory(
        self, connection_id, clean_app_db, connection_dir
    ):
        sources = _sources(clean_app_db, connection_id)

        assert [(s["file"], s["origin"]) for s in sources] == [("Q3 sales.csv", "upload")]
        for source in sources:
            assert str(connection_dir) in source["path"]

    def test_no_path_reaches_the_response(self, client, token, connection_id, uploads_dir):
        body = client.get("/connections", headers=_auth(token)).text

        assert str(uploads_dir) not in body
        assert "sources" not in body

    def test_an_unsupported_extension_is_refused(self, client, token, clean_app_db, uploads_dir):
        r = _upload(client, token, "evil", ("payload.exe", b"MZ"))

        assert r.status_code == 415

    def test_an_oversized_upload_is_refused(
        self, client, token, clean_app_db, uploads_dir, monkeypatch
    ):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "max_upload_bytes", 32, raising=False)

        r = _upload(client, token, "big", ("big.csv", CSV.encode()))

        assert r.status_code == 413
        assert "big.csv" in r.json()["detail"]

    def test_a_file_that_is_not_a_spreadsheet_is_refused(
        self, client, token, clean_app_db, uploads_dir
    ):
        r = _upload(client, token, "junk", ("junk.parquet", b"not a parquet file at all"))

        assert r.status_code == 400
        assert r.json()["error"] == "junk.parquet could not be read as a spreadsheet"
        assert not any((uploads_dir / "t_test").iterdir())

    @pytest.mark.parametrize("count", [0, 21])
    def test_a_request_carries_one_to_twenty_files(
        self, client, token, clean_app_db, uploads_dir, count
    ):
        files = [(f"part{i}.csv", STOCK.encode()) for i in range(count)]

        r = _upload(client, token, "many", *files)

        assert r.status_code == 422
        assert not uploads_dir.joinpath("t_test").exists()

    def test_another_tenant_cannot_see_it(self, client, other_token, connection_id):
        assert client.get("/connections", headers=_auth(other_token)).json() == []


class TestDataset:
    def test_several_files_in_one_request_make_one_connection(
        self, client, token, clean_app_db, uploads_dir
    ):
        r = _upload(
            client,
            token,
            "July",
            ("Q3 sales.csv", CSV.encode()),
            ("dealers.csv", DEALERS.encode()),
            ("stock.csv", STOCK.encode()),
        )

        assert r.status_code == 201, r.text
        body = r.json()
        assert (body["file_count"], body["selected_tables"], body["total_tables"]) == (3, 3, 3)
        tables = _tables(client, token, body["id"])
        assert {name: (t["file"], t["selected"]) for name, t in tables.items()} == {
            "dealers": ("dealers.csv", True),
            "q3_sales": ("Q3 sales.csv", True),
            "stock": ("stock.csv", True),
        }

    def test_added_files_arrive_unselected(self, client, token, connection_id):
        r = _add(
            client,
            token,
            connection_id,
            ("dealers.csv", DEALERS.encode()),
            ("stock.csv", STOCK.encode()),
        )

        assert r.status_code == 200, r.text
        assert {t["name"]: (t["file"], t["selected"]) for t in r.json()["tables"]} == {
            "dealers": ("dealers.csv", False),
            "q3_sales": ("Q3 sales.csv", True),
            "stock": ("stock.csv", False),
        }
        assert client.get("/connections", headers=_auth(token)).json()[0]["file_count"] == 3

    def test_a_file_already_in_the_dataset_is_refused(
        self, client, token, connection_id, connection_dir
    ):
        before = sorted(connection_dir.iterdir())

        r = _add(client, token, connection_id, ("Q3 sales.csv", CSV.encode()))

        assert r.status_code == 400
        assert "Q3 sales.csv" in r.json()["error"]
        assert sorted(connection_dir.iterdir()) == before

    def test_removing_a_file_takes_its_tables_away(self, client, token, clean_app_db, uploads_dir):
        connection_id = _upload(
            client, token, "July", ("Q3 sales.csv", CSV.encode()), ("dealers.csv", DEALERS.encode())
        ).json()["id"]
        parquet = [
            Path(s["path"])
            for s in _sources(clean_app_db, connection_id)
            if s["file"] == "dealers.csv"
        ]

        r = client.delete(f"/connections/{connection_id}/files/dealers.csv", headers=_auth(token))

        assert r.status_code == 200, r.text
        assert [t["name"] for t in r.json()["tables"]] == ["q3_sales"]
        assert parquet
        assert not any(p.exists() for p in parquet)
        names = [n for n, _ in _ask(client, token, connection_id, "select * from dealers", "rm-1")]
        assert "sql" not in names
        assert "rows" not in names
        assert names[-1] == "done"

    def test_removing_the_only_file_of_a_batch_removes_its_directory(
        self, client, token, connection_id, connection_dir
    ):
        before = sorted(connection_dir.iterdir())
        assert _add(client, token, connection_id, ("dealers.csv", DEALERS.encode())).is_success
        assert len(list(connection_dir.iterdir())) == 2

        r = client.delete(f"/connections/{connection_id}/files/dealers.csv", headers=_auth(token))

        assert r.status_code == 200, r.text
        assert sorted(connection_dir.iterdir()) == before

    def test_the_last_file_cannot_be_removed(self, client, token, connection_id):
        r = client.delete(f"/connections/{connection_id}/files/Q3 sales.csv", headers=_auth(token))

        assert r.status_code == 400
        assert list(_tables(client, token, connection_id)) == ["q3_sales"]

    def test_removing_a_file_the_dataset_does_not_hold_is_a_404(self, client, token, connection_id):
        r = client.delete(f"/connections/{connection_id}/files/nope.csv", headers=_auth(token))

        assert r.status_code == 404

    def test_a_batch_with_one_bad_file_changes_nothing(
        self, client, token, connection_id, connection_dir
    ):
        before = sorted(connection_dir.iterdir())

        r = _add(
            client,
            token,
            connection_id,
            ("dealers.csv", DEALERS.encode()),
            ("stock.parquet", b"not a parquet file at all"),
        )

        assert r.status_code == 400
        assert "stock.parquet" in r.json()["error"]
        assert sorted(connection_dir.iterdir()) == before
        assert list(_tables(client, token, connection_id)) == ["q3_sales"]

    def test_a_dataset_cannot_grow_past_its_cap(
        self, client, token, clean_app_db, connection_id, connection_dir, monkeypatch
    ):
        from app.config import get_settings

        held = sum(p.stat().st_size for p in connection_dir.rglob("*.parquet"))
        monkeypatch.setattr(get_settings(), "max_dataset_bytes", held, raising=False)
        sources, before = _sources(clean_app_db, connection_id), sorted(connection_dir.iterdir())

        r = _add(client, token, connection_id, ("dealers.csv", DEALERS.encode()))

        assert r.status_code == 400
        assert "limited" in r.json()["error"]
        assert _sources(clean_app_db, connection_id) == sources
        assert sorted(connection_dir.iterdir()) == before
        assert list(_tables(client, token, connection_id)) == ["q3_sales"]

    def test_a_database_connection_holds_no_files(self, client, token, clean_app_db):
        from app.db.models import Connection
        from app.security import vault
        from app.services.connections import ensure_tenant

        ensure_tenant(clean_app_db, "t_test")
        conn = Connection(
            tenant_id="t_test",
            name="db",
            kind="postgres",
            secret_enc=vault.encrypt({"dsn": "postgresql://nobody@nowhere/db"}),
        )
        clean_app_db.add(conn)
        clean_app_db.commit()

        added = _add(client, token, conn.id, ("dealers.csv", DEALERS.encode()))
        removed = client.delete(f"/connections/{conn.id}/files/dealers.csv", headers=_auth(token))

        assert (added.status_code, removed.status_code) == (400, 400)

    def test_deleting_the_connection_removes_every_batch(
        self, client, token, connection_id, connection_dir
    ):
        assert _add(client, token, connection_id, ("dealers.csv", DEALERS.encode())).is_success
        assert len(list(connection_dir.iterdir())) == 2

        r = client.delete(f"/connections/{connection_id}", headers=_auth(token))

        assert r.status_code == 204
        assert not connection_dir.exists()


class TestAsking:
    def test_a_question_about_the_file_streams_the_whole_contract(
        self, client, token, connection_id, clean_app_db
    ):
        from tests.integration.test_runs_api import _parse_sse

        model = _script(
            "select region, sum(revenue_inr) as revenue from q3_sales group by region",
            "West earned the most.",
        )
        with patch("app.agent.graph.get_llm", return_value=model):
            r = client.post(
                "/runs",
                headers=_auth(token),
                json={
                    "connection_id": connection_id,
                    "thread_id": "file-1",
                    "question": "Which region earned the most?",
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
        assert payload["rows"]["columns"] == ["region", "revenue"]
        # DuckDB sniffs a decimal CSV column as DOUBLE, so it crosses the wire as a JSON
        # number. A Postgres NUMERIC becomes a Decimal and crosses as an exact string.
        assert sorted(payload["rows"]["rows"]) == [["East", 1800.0], ["West", 4000.75]]

    def test_a_question_can_join_two_files(self, client, token, clean_app_db, uploads_dir):
        connection_id = _upload(
            client, token, "July", ("Q3 sales.csv", CSV.encode()), ("dealers.csv", DEALERS.encode())
        ).json()["id"]

        events = _ask(
            client,
            token,
            connection_id,
            "select d.dealer, sum(s.units) as units from q3_sales s "
            "join dealers d on d.region = s.region group by d.dealer",
            "file-join",
        )
        names = [n for n, _ in events]
        payload = dict(events)

        assert "error" not in names, payload.get("error")
        assert "join dealers" in payload["sql"]["sql"].lower()
        assert payload["rows"]["columns"] == ["dealer", "units"]
        assert sorted(payload["rows"]["rows"]) == [["Nashik EV", 4], ["Pune Motors", 16]]

    def test_the_guard_refuses_a_query_that_reaches_for_a_file(
        self, client, token, connection_id, clean_app_db
    ):
        """Both layers hold: the guard rejects the table function, and the engine would refuse
        it anyway because external access is off once the tables are materialised."""
        from tests.integration.test_runs_api import _parse_sse

        model = _script(
            "select * from read_csv_auto('C:/Windows/win.ini')",
            "I cannot read that.",
        )
        with patch("app.agent.graph.get_llm", return_value=model):
            r = client.post(
                "/runs",
                headers=_auth(token),
                json={
                    "connection_id": connection_id,
                    "thread_id": "file-2",
                    "question": "Show me the system files",
                },
            )

        events = _parse_sse(r.text)
        names = [n for n, _ in events]

        assert "sql" not in names, "a rejected statement was reported as executed SQL"
        assert "rows" not in names
        assert names[-1] == "done"

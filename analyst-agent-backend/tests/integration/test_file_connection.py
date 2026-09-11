"""Upload a spreadsheet, then ask a question about it. Phase 5's done-line.

The model is scripted, so this costs no quota; what it proves is the upload route, the ingest,
the connector, the duckdb dialect through the guard, and the frozen SSE contract.
"""

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


def _upload(client, token: str, name: str, filename: str, body: bytes):
    return client.post(
        "/connections/file",
        headers=_auth(token),
        data={"name": name},
        files={"file": (filename, body, "text/csv")},
    )


@pytest.fixture
def uploads_dir(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "file_store_dir", str(tmp_path), raising=False)
    return tmp_path


@pytest.fixture
def connection_id(client, token, clean_app_db, uploads_dir) -> str:
    r = _upload(client, token, "Q3 sales", "Q3 sales.csv", CSV.encode())
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestUpload:
    def test_it_registers_a_file_connection(self, client, token, connection_id):
        listed = client.get("/connections", headers=_auth(token)).json()

        assert [c["kind"] for c in listed] == ["file"]
        assert listed[0]["name"] == "Q3 sales"

    def test_the_stored_paths_are_under_this_tenants_directory(
        self, client, token, connection_id, clean_app_db, uploads_dir
    ):
        from app.db.models import Connection
        from app.security import vault

        secret = vault.decrypt(clean_app_db.get(Connection, connection_id).secret_enc)

        assert secret["filename"] == "Q3 sales.csv"
        for source in secret["sources"]:
            assert str(uploads_dir / "t_test" / connection_id) in source["path"]

    def test_no_path_reaches_the_response(self, client, token, connection_id, uploads_dir):
        body = client.get("/connections", headers=_auth(token)).text

        assert str(uploads_dir) not in body
        assert "sources" not in body

    def test_an_unsupported_extension_is_refused(self, client, token, clean_app_db, uploads_dir):
        r = _upload(client, token, "evil", "payload.exe", b"MZ")

        assert r.status_code == 415

    def test_an_oversized_upload_is_refused(
        self, client, token, clean_app_db, uploads_dir, monkeypatch
    ):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "max_upload_bytes", 32, raising=False)

        r = _upload(client, token, "big", "big.csv", CSV.encode())

        assert r.status_code == 413

    def test_a_file_that_is_not_a_spreadsheet_is_refused(
        self, client, token, clean_app_db, uploads_dir
    ):
        r = _upload(client, token, "junk", "junk.parquet", b"not a parquet file at all")

        assert r.status_code == 400
        assert "spreadsheet" in r.json()["error"]

    def test_another_tenant_cannot_see_it(self, client, other_token, connection_id):
        assert client.get("/connections", headers=_auth(other_token)).json() == []


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

import pytest
from sqlalchemy import text

from tests.integration.accounts import create_account

DEMO_DSN = "postgresql+psycopg://analyst_ro:ro@localhost:5432/demo"


@pytest.fixture(scope="session")
def demo_dsn() -> str:
    return DEMO_DSN


@pytest.fixture
def clean_app_db():
    """Integration tests share one App DB, so each starts from a known state."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        # Order matters: users and connections reference tenants, and connection_tables and
        # runs reference connections.
        db.execute(text("DELETE FROM users"))
        db.execute(text("DELETE FROM runs"))
        db.execute(text("DELETE FROM connection_tables"))
        db.execute(text("DELETE FROM dataset_files"))
        db.execute(text("DELETE FROM dataset_sources"))
        db.execute(text("DELETE FROM connections"))
        db.execute(text("DELETE FROM tenants"))
        db.commit()
        yield db
    finally:
        db.close()


@pytest.fixture
def token(clean_app_db) -> str:
    """A member of `t_test`. Depends on `clean_app_db` so the wipe cannot run after it and
    delete the account the token names."""
    return create_account(clean_app_db, "t_test")


@pytest.fixture
def other_token(clean_app_db) -> str:
    return create_account(clean_app_db, "t_other")


@pytest.fixture(autouse=True)
def mcp_in_process(monkeypatch):
    """Send MCP calls straight to the server's own tool functions instead of over HTTP.

    The MCP server is a separate process that reads its own settings, so under the suite it
    holds a different `CREDENTIAL_ENCRYPTION_KEY` than the one these tests encrypt with, and
    every connection would fail to open. Dispatching in-process runs the real tools, the real
    guard and the real catalog readers against the test's own settings.

    What this does not cover is the transport, so it is not the only thing covering it:
    `test_database_mcp.py` drives the tools through the server's own context, and `probe_mcp`
    checks the wire at boot.
    """
    from mcp.server.auth.provider import AccessToken
    from pydantic import BaseModel

    from app import database_mcp, mcp_client

    def as_wire(value):
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [as_wire(v) for v in value]
        return value

    tools = {
        "list_tables": database_mcp.list_tables,
        "read_tables": database_mcp.read_tables,
        "table_stats": database_mcp.table_stats,
        "run_select": database_mcp.run_select,
    }

    def call(tenant_id, connection_id, tool, args):
        monkeypatch.setattr(
            database_mcp,
            "get_access_token",
            lambda: AccessToken(
                token="test",
                client_id="analyst-agent",
                scopes=["database:read"],
                claims={"tenant_id": tenant_id, "connection_id": connection_id},
            ),
        )
        return as_wire(tools[tool](**args))

    monkeypatch.setattr(mcp_client, "call", call)


def http_error(status: int, reason: str):
    import json

    import httplib2
    from googleapiclient.errors import HttpError

    body = {"error": {"code": status, "message": reason, "errors": [{"reason": reason}]}}
    return HttpError(httplib2.Response({"status": status}), json.dumps(body).encode())


class FakeDrive:
    email = "reader@analyst-test.iam.gserviceaccount.com"

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.content: dict[str, bytes] = {}
        self.tabs: dict[str, list[dict]] = {}
        self.values: dict[str, dict[str, list[list]]] = {}
        self.too_big_to_export: set[str] = set()
        self.calls: list[tuple[str, str]] = []
        self.keys: dict[str, str] = {}

    def __call__(self, tenant_id: str, keys: dict[str, str] | None = None) -> "FakeDrive":
        self.keys = dict(keys or {})
        return self

    def add(
        self,
        item_id: str,
        name: str,
        mime: str,
        parent: str | None = None,
        content: bytes = b"",
        sharer: str | None = None,
        version: str = "v1",
    ) -> dict:
        item = {
            "id": item_id,
            "name": name,
            "mimeType": mime,
            "parents": [parent] if parent else [],
            "size": str(len(content)),
            "modifiedTime": f"2026-09-{version}",
            "capabilities": {"canDownload": True},
        }
        if not mime.startswith("application/vnd.google-apps"):
            item["md5Checksum"] = f"md5-{version}"
        if sharer:
            item["sharingUser"] = {"emailAddress": sharer}
        self.items[item_id] = item
        self.content[item_id] = content
        return item

    def get(self, file_id: str) -> dict:
        self.calls.append(("get", file_id))
        if file_id not in self.items:
            raise http_error(404, "notFound")
        return self.items[file_id]

    def get_many(self, ids: list[str]) -> dict[str, dict]:
        self.calls.append(("get_many", ",".join(ids)))
        return {i: self.items[i] for i in ids if i in self.items}

    def children(self, folder_ids: list[str]) -> list[dict]:
        self.calls.append(("children", ",".join(folder_ids)))
        return [item for item in self.items.values() if set(item["parents"]) & set(folder_ids)]

    def download(self, file_id: str, dest) -> None:
        self.calls.append(("download", file_id))
        dest.write_bytes(self.content[file_id])

    def export_xlsx(self, file_id: str, dest) -> None:
        self.calls.append(("export", file_id))
        if file_id in self.too_big_to_export:
            raise http_error(403, "exportSizeLimitExceeded")
        dest.write_bytes(self.content[file_id])

    def sheet_tabs(self, spreadsheet_id: str) -> list[dict]:
        self.calls.append(("tabs", spreadsheet_id))
        return self.tabs[spreadsheet_id]

    def sheet_values(self, spreadsheet_id: str, titles: list[str]) -> dict[str, list[list]]:
        self.calls.append(("values", spreadsheet_id))
        return {title: self.values[spreadsheet_id][title] for title in titles}

    def downloads(self) -> list[str]:
        return [item for call, item in self.calls if call in ("download", "export", "values")]


@pytest.fixture
def drive(monkeypatch) -> FakeDrive:
    from app.services import sources, sync

    fake = FakeDrive()
    monkeypatch.setattr(sources, "Drive", fake)
    monkeypatch.setattr(sync, "Drive", fake)
    return fake

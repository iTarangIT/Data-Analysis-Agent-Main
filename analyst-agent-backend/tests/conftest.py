import json
import os

import pytest
from cryptography.fernet import Fernet

from tests import supabase_tokens

# Settings are read at import time, so these must be set before any `app.*` import. Every
# `app` import in this file therefore lives inside a fixture body.
# Assigned, not defaulted: the issuer every test token carries has to match, whatever the
# developer's shell or .env points at.
os.environ["SUPABASE_URL"] = supabase_tokens.SUPABASE_URL
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("APP_DB_URL", "postgresql+psycopg://app:app@localhost:5432/analyst")
os.environ.setdefault("CHECKPOINT_DB_URL", "postgresql://ckpt:ckpt@localhost:5432/checkpoints")
os.environ.setdefault("MCP_JWT_SECRET", "test-mcp-secret-test-mcp-secret")
# No MCP server runs under the suite; the tests that need one stub the client.
os.environ.setdefault("MCP_STARTUP_PROBE", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")
# Off by default so the suite opens no store connection and every test that does not ask for
# memory behaves exactly as it did before there was any. The tests that want one say so:
# the unit tests hand `build_agent` an `InMemoryStore`, and `test_memory_store.py` asks for
# Postgres.
os.environ.setdefault("MEMORY_BACKEND", "off")


@pytest.fixture(autouse=True)
def supabase_jwks(monkeypatch):
    """Serve the test key set instead of fetching the project's. Only the HTTP call is
    replaced; picking the key by `kid` and verifying with it stay real."""
    from jwt import PyJWKClient

    monkeypatch.setattr(PyJWKClient, "fetch_data", lambda self: supabase_tokens.jwks())


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


STATEMENT_HEADER = ["Date", "Particulars", "Amount", "Balance"]


def _statement_rows(count: int) -> list[list[str]]:
    return [
        [
            f"{day % 28 + 1:02d}/07/2026",
            f"Invoice {day}",
            f"{day % 90 + 1},23,456.50" if day % 2 else f"Rs. {day},500.00",
            f"{day * 100:,}.00 {'Dr' if day % 3 else 'Cr'}",
        ]
        for day in range(1, count + 1)
    ]


@pytest.fixture
def statement_pdf(tmp_path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    path = tmp_path / "statement.pdf"
    table = Table([STATEMENT_HEADER, *_statement_rows(110)], repeatRows=1)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    SimpleDocTemplate(str(path), pagesize=A4).build([table])
    return path


@pytest.fixture
def narrative_pdf(tmp_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

    path = tmp_path / "notes.pdf"
    body = getSampleStyleSheet()["BodyText"]
    story = [Paragraph(f"Dealer {i} sold more cells this month than last.", body) for i in range(8)]
    story += [PageBreak(), Paragraph("Stock is low at the Pune warehouse.", body)]
    SimpleDocTemplate(str(path), pagesize=A4).build(story)
    return path


@pytest.fixture
def scanned_pdf(tmp_path):
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    path = tmp_path / "scan.pdf"
    page = canvas.Canvas(str(path))
    page.drawImage(ImageReader(Image.new("RGB", (400, 200), "white")), 72, 500)
    page.showPage()
    page.save()
    return path


@pytest.fixture
def google_credentials(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from pydantic import SecretStr

    from app.config import get_settings

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    info = {
        "type": "service_account",
        "project_id": "analyst-test",
        "private_key_id": "k1",
        "private_key": key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        "client_email": "reader@analyst-test.iam.gserviceaccount.com",
        "client_id": "1",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    secret = SecretStr(json.dumps(info))
    monkeypatch.setattr(get_settings(), "google_service_account_json", secret, raising=False)
    return info


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[tuple[str, str]] = []
        self.down = False

    def __call__(self, request):
        import httpx

        if self.down:
            raise httpx.ConnectError("storage is down", request=request)
        assert request.headers["apikey"] == "sb_secret_test"
        assert "authorization" not in request.headers
        path = request.url.path.removeprefix("/storage/v1/object/")
        self.requests.append((request.method, path))
        if request.method == "POST":
            self.objects[path.removeprefix("datasets/")] = request.read()
            return httpx.Response(200, json={"Key": path})
        if request.method == "GET":
            body = self.objects.get(path.removeprefix("authenticated/datasets/"))
            if body is None:
                return httpx.Response(400, json={"error": "not_found"})
            return httpx.Response(200, content=body)
        for key in json.loads(request.content)["prefixes"]:
            self.objects.pop(key, None)
        return httpx.Response(200, json=[])


@pytest.fixture
def supabase_storage(tmp_path, monkeypatch):
    import httpx
    from pydantic import SecretStr

    from app.config import get_settings
    from app.connectors import storage

    settings = get_settings()
    monkeypatch.setattr(settings, "file_store_backend", "supabase", raising=False)
    monkeypatch.setattr(settings, "supabase_secret_key", SecretStr("sb_secret_test"), raising=False)
    monkeypatch.setattr(settings, "file_store_dir", str(tmp_path), raising=False)
    storage._client.cache_clear()
    fake = FakeStorage()
    monkeypatch.setattr(storage._client(), "_transport", httpx.MockTransport(fake))
    yield fake
    storage._client.cache_clear()

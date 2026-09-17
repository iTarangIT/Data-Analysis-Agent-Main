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

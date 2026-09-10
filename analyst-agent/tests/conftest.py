import os

import pytest
from cryptography.fernet import Fernet

# Settings are read at import time, so these must be set before any `app.*` import. Every
# `app` import in this file therefore lives inside a fixture body.
os.environ.setdefault("OPENROUTER_API_KEY", "test")
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret")
os.environ.setdefault("APP_DB_URL", "postgresql+psycopg://app:app@localhost:5432/analyst")
os.environ.setdefault("CHECKPOINT_DB_URL", "postgresql://ckpt:ckpt@localhost:5432/checkpoints")
os.environ.setdefault("LANGSMITH_TRACING", "false")


@pytest.fixture
def token() -> str:
    from jose import jwt

    from app.config import get_settings

    return jwt.encode(
        {"tenant_id": "t_test", "sub": "u_test"},
        get_settings().jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)

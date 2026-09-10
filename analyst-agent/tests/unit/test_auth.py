import pytest
from jose import jwt

from app.config import get_settings
from app.security.auth import decode_token


def _sign(payload: dict, secret: str | None = None) -> str:
    secret = secret or get_settings().jwt_secret.get_secret_value()
    return jwt.encode(payload, secret, algorithm="HS256")


def test_decodes_tenant_and_user():
    ctx = decode_token(_sign({"tenant_id": "t1", "sub": "u1"}))
    assert (ctx.tenant_id, ctx.user_id) == ("t1", "u1")


def test_rejects_foreign_signature():
    with pytest.raises(ValueError):
        decode_token(_sign({"tenant_id": "t1", "sub": "u1"}, secret="a-different-secret-entirely"))


@pytest.mark.parametrize("payload", [{"sub": "u1"}, {"tenant_id": "t1"}, {}])
def test_rejects_token_without_tenant_or_subject(payload):
    with pytest.raises(ValueError, match="missing tenant_id or sub"):
        decode_token(_sign(payload))

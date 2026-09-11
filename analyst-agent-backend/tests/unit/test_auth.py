from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from app.config import get_settings
from app.security.auth import (
    decode_token,
    hash_refresh_token,
    mint_access_token,
    new_refresh_token,
)


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


def test_a_minted_access_token_decodes_to_the_same_context():
    ctx = decode_token(mint_access_token(tenant_id="t1", user_id="u1"))
    assert (ctx.tenant_id, ctx.user_id) == ("t1", "u1")


def test_a_minted_access_token_carries_an_expiry():
    payload = jwt.get_unverified_claims(mint_access_token(tenant_id="t1", user_id="u1"))
    assert payload["exp"] > payload["iat"]


def test_an_expired_token_is_rejected():
    expired = _sign(
        {
            "tenant_id": "t1",
            "sub": "u1",
            "exp": int((datetime.now(UTC) - timedelta(minutes=1)).timestamp()),
        }
    )
    with pytest.raises(ValueError):
        decode_token(expired)


def test_a_token_without_an_expiry_is_still_accepted():
    # The eval harness and the test fixtures hand-mint tokens with no `exp`, and every route
    # they exercise must keep working.
    assert decode_token(_sign({"tenant_id": "t1", "sub": "u1"})).tenant_id == "t1"


def test_refresh_tokens_are_opaque_not_jwts():
    # Load-bearing: `decode_token` accepts any signed token carrying tenant_id and sub, so a
    # JWT refresh token would be accepted as a 30-day access token for the whole API.
    with pytest.raises(ValueError):
        decode_token(new_refresh_token())


def test_each_refresh_token_is_unique():
    assert len({new_refresh_token() for _ in range(100)}) == 100


def test_refresh_tokens_are_hashed_deterministically():
    # Deterministic so the column can carry a unique index and lookup is one probe, where
    # argon2's random salt would force a full scan.
    raw = new_refresh_token()
    assert hash_refresh_token(raw) == hash_refresh_token(raw)
    assert hash_refresh_token(raw) != hash_refresh_token(new_refresh_token())


def test_the_refresh_token_hash_does_not_contain_the_token():
    raw = new_refresh_token()
    assert raw not in hash_refresh_token(raw)
    assert len(hash_refresh_token(raw)) == 64  # sha256 hex, and what String(64) expects

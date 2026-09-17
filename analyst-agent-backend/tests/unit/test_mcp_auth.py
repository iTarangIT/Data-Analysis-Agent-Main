"""The token is the whole tenancy mechanism for the MCP server.

Nothing in a tool's arguments names a connection, so what this token says is the only thing
deciding which customer database a call can reach. A token that verified when it should not
would be a cross-tenant read.
"""

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from app.config import get_settings
from app.mcp_auth import ISSUER, MCPTokenVerifier, mint_mcp_token
from tests import supabase_tokens


def _verify(token: str):
    import asyncio

    return asyncio.run(MCPTokenVerifier().verify_token(token))


def _forge(**overrides) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "iss": ISSUER,
        "aud": str(s.database_mcp_url),
        "sub": "analyst-agent",
        "iat": now,
        "exp": now + timedelta(seconds=60),
        "tenant_id": "t_a",
        "connection_id": "c1",
    }
    payload.update(overrides)
    return jwt.encode(payload, s.mcp_jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm)


def test_a_minted_token_carries_the_connection_it_was_minted_for():
    verified = _verify(mint_mcp_token(tenant_id="t_a", connection_id="c1"))

    assert verified is not None
    assert (verified.claims["tenant_id"], verified.claims["connection_id"]) == ("t_a", "c1")
    assert verified.scopes == ["database:read"]


def test_the_probe_token_names_no_tenant_and_no_connection():
    """`probe_mcp` runs at boot with nobody's credentials. It must not be able to open a
    database, and `_database` refuses it because these claims are absent."""
    verified = _verify(mint_mcp_token())

    assert verified is not None
    assert "tenant_id" not in verified.claims
    assert "connection_id" not in verified.claims


def test_a_user_access_token_is_refused():
    """A stolen Supabase session must not be replayable here, even one carrying MCP-shaped
    claims. If this ever passes, a user token can open any connection it names."""
    s = get_settings()
    user_token = supabase_tokens.sign(
        supabase_tokens.claims()
        | {"iss": ISSUER, "aud": str(s.database_mcp_url), "tenant_id": "t_a", "connection_id": "c1"}
    )

    assert _verify(user_token) is None


def test_a_token_signed_with_any_other_secret_is_refused():
    forged = jwt.encode(
        {
            "iss": ISSUER,
            "aud": str(get_settings().database_mcp_url),
            "tenant_id": "t_a",
            "connection_id": "c1",
        },
        "not-the-mcp-secret-not-the-mcp-secret",
        algorithm=get_settings().jwt_algorithm,
    )

    assert _verify(forged) is None


def test_an_expired_token_is_refused():
    past = datetime.now(UTC) - timedelta(seconds=10)
    assert _verify(_forge(exp=past, iat=past - timedelta(seconds=60))) is None


def test_a_token_for_another_audience_is_refused():
    assert _verify(_forge(aud="http://somewhere-else/mcp")) is None


def test_a_token_from_another_issuer_is_refused():
    assert _verify(_forge(iss="http://not-us")) is None


@pytest.mark.parametrize("garbage", ["", "not-a-token", "a.b.c"])
def test_nonsense_is_refused_rather_than_raising(garbage):
    assert _verify(garbage) is None

from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier

from app.config import get_settings

# One value: the JWT `iss` claim the verifier checks, and the issuer the server advertises in
# its OAuth metadata. They were two spellings of the same idea, which works only for as long as
# nobody reads the metadata.
ISSUER = "http://analyst-agent"


def mint_mcp_token(*, tenant_id: str | None = None, connection_id: str | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "iss": ISSUER,
        "aud": str(settings.database_mcp_url),
        "sub": "analyst-agent",
        "iat": now,
        "exp": now + timedelta(seconds=settings.mcp_token_ttl_seconds),
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    if connection_id is not None:
        payload["connection_id"] = connection_id
    return jwt.encode(
        payload,
        settings.mcp_jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


class MCPTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        settings = get_settings()
        try:
            claims = jwt.decode(
                token,
                settings.mcp_jwt_secret.get_secret_value(),
                algorithms=[settings.jwt_algorithm],
                audience=str(settings.database_mcp_url),
                issuer=ISSUER,
            )
        except JWTError:
            return None
        return AccessToken(
            token=token,
            client_id="analyst-agent",
            scopes=["database:read"],
            expires_at=claims.get("exp"),
            resource=str(settings.database_mcp_url),
            subject=claims.get("sub"),
            claims=claims,
        )

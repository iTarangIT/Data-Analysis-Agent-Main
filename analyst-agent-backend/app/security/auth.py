import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from app.config import get_settings


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    user_id: str


def decode_token(token: str) -> TenantContext:
    """Verify an agent JWT minted by analyst-web and return its tenant context.

    Raises ValueError on any invalid, expired or incomplete token.
    """
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret.get_secret_value(), algorithms=[s.jwt_algorithm])
    except JWTError as e:
        raise ValueError(f"invalid token: {e}") from e

    if "tenant_id" not in payload or "sub" not in payload:
        raise ValueError("token missing tenant_id or sub")

    return TenantContext(tenant_id=payload["tenant_id"], user_id=payload["sub"])


def mint_access_token(*, tenant_id: str, user_id: str) -> str:
    """Mint the access token `decode_token` above already accepts.

    Deliberately the same claim shape this service has always taken, so adding real sign-in
    changed no route and invalidated no hand-minted token.
    """
    s = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "tenant_id": tenant_id,
            "sub": user_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=s.access_token_ttl_minutes)).timestamp()),
        },
        s.jwt_secret.get_secret_value(),
        algorithm=s.jwt_algorithm,
    )


def new_refresh_token() -> str:
    """A refresh token is opaque, never a JWT.

    `decode_token` accepts any correctly signed token carrying tenant_id and sub, so a JWT
    refresh token would be accepted as a bearer and hand out thirty days of access to the whole
    API. A random string is not a valid JWT, so presenting one as a bearer simply 401s.
    """
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """SHA-256, not Argon2.

    The token is 256 bits of CSPRNG output, so there is nothing to brute-force and a slow KDF
    would only cost every active user 100ms every fifteen minutes. It also has to be
    deterministic: Argon2 salts randomly, so finding a row would mean scanning the table
    instead of probing a unique index.
    """
    return hashlib.sha256(token.encode()).hexdigest()

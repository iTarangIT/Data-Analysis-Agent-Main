from dataclasses import dataclass

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

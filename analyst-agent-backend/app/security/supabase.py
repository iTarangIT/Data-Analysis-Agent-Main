"""Verifies the access tokens Supabase Auth issues. The only way a user proves who they are.

The project signs with an asymmetric key (ES256), so a token is checked against the public
keys Supabase publishes, with no shared secret and no call to Supabase per request.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.config import get_settings

# Named, never read from the token header: letting the token pick its own algorithm is how an
# HMAC token signed with a public key gets accepted.
_ALGORITHMS = ["ES256", "RS256"]
# Supabase's edge caches the key set for ten minutes, so holding it longer here would only
# delay a key revocation. An unknown `kid` refetches at once regardless.
_JWKS_LIFESPAN_S = 600
# Supabase's clock and this machine's rarely agree to the second.
_LEEWAY_S = 30


@dataclass(frozen=True)
class Identity:
    """Who Supabase says is calling. Says nothing about which tenant they belong to."""

    sub: str
    email: str
    email_verified: bool
    name: str | None


@lru_cache
def _jwks_client() -> PyJWKClient:
    return PyJWKClient(
        get_settings().supabase_jwks_url, cache_jwk_set=True, lifespan=_JWKS_LIFESPAN_S
    )


def verify_access_token(token: str) -> Identity:
    """Return the verified identity behind a Supabase access token.

    Raises ValueError on anything that is not a live, signed, signed-in user's token.
    """
    s = get_settings()
    try:
        key = _jwks_client().get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=_ALGORITHMS,
            audience="authenticated",
            issuer=s.supabase_issuer,
            leeway=_LEEWAY_S,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError as e:
        raise ValueError(f"invalid token: {e}") from e

    # `aud` alone would admit a service-role token minted for the same audience.
    if claims.get("role") != "authenticated":
        raise ValueError("token is not a signed-in user's")
    if claims.get("is_anonymous"):
        raise ValueError("anonymous sessions cannot use this service")

    email = claims.get("email")
    if not isinstance(email, str) or not email:
        raise ValueError("token carries no email")

    metadata = claims.get("user_metadata") or {}
    return Identity(
        sub=claims["sub"],
        email=email.strip().lower(),
        # Strictly `True`: absent or anything else is unverified, and linking to an existing
        # account by email is only safe for an address its owner has proven.
        email_verified=metadata.get("email_verified") is True,
        name=metadata.get("full_name") or metadata.get("name"),
    )

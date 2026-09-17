"""A stand-in for Supabase Auth: one ES256 key pair, its JWKS, and tokens shaped like the real
ones (https://supabase.com/docs/guides/auth/jwt-fields).

Only the network fetch of the JWKS is replaced (see `tests/conftest.py`). Key selection by
`kid`, signature checks and claim validation all run through the real code.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

SUPABASE_URL = "https://test-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
KID = "test-signing-key"

_private_key = ec.generate_private_key(ec.SECP256R1())


def jwks() -> dict[str, Any]:
    jwk = ECAlgorithm.to_jwk(_private_key.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": KID, "alg": "ES256", "use": "sig", "key_ops": ["verify"]}]}


def claims(
    *,
    sub: str | None = None,
    email: str = "owner@example.com",
    email_verified: bool = True,
    name: str | None = "Owner Person",
    expires_in: timedelta = timedelta(hours=1),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    metadata: dict[str, Any] = {"email_verified": email_verified}
    if name is not None:
        metadata["full_name"] = name
    return {
        "iss": ISSUER,
        "aud": "authenticated",
        "sub": sub or str(uuid.uuid4()),
        "exp": int((now + expires_in).timestamp()),
        "iat": int(now.timestamp()),
        "role": "authenticated",
        "aal": "aal1",
        "session_id": str(uuid.uuid4()),
        "email": email,
        "phone": "",
        "is_anonymous": False,
        "app_metadata": {"provider": "email", "providers": ["email"]},
        "user_metadata": metadata,
    }


def sign(payload: dict[str, Any], *, key: Any = None, kid: str = KID) -> str:
    return jwt.encode(payload, key or _private_key, algorithm="ES256", headers={"kid": kid})


def mint(**kwargs: Any) -> str:
    """A valid access token for a (by default new) Supabase user."""
    return sign(claims(**kwargs))

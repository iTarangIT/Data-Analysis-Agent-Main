"""The only module that sees plaintext customer credentials.

`decrypt()` is called from exactly one place, `app.connectors.registry`. Nothing it returns may
reach an API response.
"""

import json

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_f = Fernet(get_settings().credential_encryption_key.get_secret_value().encode())


def encrypt(obj: dict) -> str:
    return _f.encrypt(json.dumps(obj).encode()).decode()


def decrypt(token: str) -> dict:
    try:
        return json.loads(_f.decrypt(token.encode()))
    except InvalidToken as e:
        raise ValueError("credential decrypt failed - wrong CREDENTIAL_ENCRYPTION_KEY?") from e

"""The only module that knows how a password is hashed.

Argon2id with the current OWASP parameters. `argon2-cffi` owns the PHC string format, so
nothing here hand-rolls a salt, an encoding, or a parameter comparison.

Hashing costs roughly 50-100ms by design. Every caller must therefore be a plain `def` route
so FastAPI runs it in its threadpool: `app.services.runs` already holds the event loop for the
length of a run, and a second blocker on it would stall every other request.
"""

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError

# OWASP's current recommendation: 64 MiB, 3 passes, 4 lanes.
_hasher = PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=4, hash_len=32, salt_len=16)

# Login verifies against this when the email is unknown, so an unregistered address costs the
# same time as a wrong password and the response cannot be used to enumerate accounts.
DUMMY_HASH = _hasher.hash("an password that is never a real one")


def hash_password(password: str) -> str:
    """Return a PHC-format Argon2id hash, about 97 characters."""
    return _hasher.hash(password)


def verify(password_hash: str, password: str) -> bool:
    """Whether the password matches. False rather than raising for a malformed or empty hash,
    which is what a half-migrated or blanked row looks like."""
    try:
        return _hasher.verify(password_hash, password)
    except (Argon2Error, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Whether the hash predates the current parameters, so login can quietly upgrade it.
    False for anything unparseable: there is nothing to upgrade, and `verify` already refused it.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (Argon2Error, InvalidHashError):
        return False

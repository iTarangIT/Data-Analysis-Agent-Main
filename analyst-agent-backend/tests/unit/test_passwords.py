import pytest

from app.security import passwords

PASSWORD = "correct horse battery staple"


def test_roundtrip_verifies_the_original_password():
    assert passwords.verify(passwords.hash_password(PASSWORD), PASSWORD)


def test_hash_reveals_nothing_of_the_password():
    h = passwords.hash_password(PASSWORD)
    assert PASSWORD not in h
    assert "horse" not in h


def test_hash_uses_argon2id():
    # The PHC prefix is what the migration's String(255) and every "is it hashed" test rely on.
    assert passwords.hash_password(PASSWORD).startswith("$argon2id$")


def test_the_same_password_hashes_differently_each_time():
    # A random salt per hash, so two users with one password are not visibly identical.
    assert passwords.hash_password(PASSWORD) != passwords.hash_password(PASSWORD)


def test_a_wrong_password_does_not_verify():
    assert not passwords.verify(passwords.hash_password(PASSWORD), "wrong")


def test_a_garbage_hash_does_not_verify():
    # Reaches this whenever a soft-deleted or half-migrated row is checked; must not raise.
    assert not passwords.verify("not-a-hash", PASSWORD)


def test_an_empty_hash_does_not_verify():
    assert not passwords.verify("", PASSWORD)


def test_the_dummy_hash_verifies_against_nothing():
    # Login hashes against this when the email is unknown, so the reply takes the same time.
    assert not passwords.verify(passwords.DUMMY_HASH, PASSWORD)


def test_the_dummy_hash_is_a_real_argon2_hash():
    # If it were a placeholder string, verify would fail fast and leak the timing it exists
    # to hide.
    assert passwords.DUMMY_HASH.startswith("$argon2id$")


def test_a_current_hash_does_not_need_rehashing():
    assert not passwords.needs_rehash(passwords.hash_password(PASSWORD))


def test_a_weaker_hash_needs_rehashing():
    from argon2 import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    assert passwords.needs_rehash(weak)


def test_a_garbage_hash_does_not_need_rehashing():
    # Nothing to upgrade, and raising here would break a login that verify already refused.
    assert not passwords.needs_rehash("not-a-hash")


@pytest.mark.parametrize("bad", ["", " ", "x" * 200])
def test_any_string_can_be_hashed_and_verified(bad):
    assert passwords.verify(passwords.hash_password(bad), bad)

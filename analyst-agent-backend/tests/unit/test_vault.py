import pytest

from app.security import vault


def test_roundtrip_returns_the_original_mapping():
    assert vault.decrypt(vault.encrypt({"dsn": "x"})) == {"dsn": "x"}


def test_ciphertext_reveals_neither_key_nor_value():
    token = vault.encrypt({"dsn": "postgresql://u:p@h/db"})
    assert "dsn" not in token
    assert "postgresql" not in token
    assert "p@h" not in token


def test_the_same_secret_encrypts_differently_each_time():
    # Fernet includes a random IV, so identical input must not produce identical ciphertext.
    secret = {"dsn": "postgresql://u:p@h/db"}
    assert vault.encrypt(secret) != vault.encrypt(secret)


def test_tampered_ciphertext_is_rejected():
    token = vault.encrypt({"dsn": "x"})
    with pytest.raises(ValueError, match="decrypt failed"):
        vault.decrypt(token[:-4] + "AAAA")


def test_garbage_is_rejected():
    with pytest.raises(ValueError, match="decrypt failed"):
        vault.decrypt("not-a-fernet-token")


def test_roundtrip_preserves_nested_web_credentials():
    secret = {"url": "https://dash.example.com", "username": "u", "password": "p"}
    assert vault.decrypt(vault.encrypt(secret)) == secret

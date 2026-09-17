"""Supabase access tokens are the only credential a user holds.

Every rejection here is a way a forged or stale token could otherwise reach a tenant's data.
"""

from datetime import timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.security.supabase import verify_access_token
from tests import supabase_tokens as supa


def test_a_valid_token_names_the_supabase_user():
    identity = verify_access_token(
        supa.mint(sub="7d1c9a4e-0000-4000-8000-000000000001", email="Owner@Example.com")
    )

    assert identity.sub == "7d1c9a4e-0000-4000-8000-000000000001"
    assert identity.email == "owner@example.com"
    assert identity.email_verified is True
    assert identity.name == "Owner Person"


def test_an_unverified_email_is_reported_as_unverified():
    assert verify_access_token(supa.mint(email_verified=False)).email_verified is False


def test_a_missing_email_verified_claim_counts_as_unverified():
    payload = supa.claims()
    del payload["user_metadata"]["email_verified"]

    assert verify_access_token(supa.sign(payload)).email_verified is False


def test_a_token_signed_by_another_key_is_refused():
    stranger = ec.generate_private_key(ec.SECP256R1())

    with pytest.raises(ValueError):
        verify_access_token(supa.sign(supa.claims(), key=stranger))


def test_a_token_naming_an_unknown_key_is_refused():
    with pytest.raises(ValueError):
        verify_access_token(supa.sign(supa.claims(), kid="rotated-away"))


def test_an_expired_token_is_refused():
    with pytest.raises(ValueError):
        verify_access_token(supa.mint(expires_in=timedelta(minutes=-5)))


def test_a_token_from_another_project_is_refused():
    payload = supa.claims() | {"iss": "https://another-project.supabase.co/auth/v1"}

    with pytest.raises(ValueError):
        verify_access_token(supa.sign(payload))


def test_an_anon_key_token_is_refused():
    payload = supa.claims() | {"aud": "anon", "role": "anon"}

    with pytest.raises(ValueError):
        verify_access_token(supa.sign(payload))


def test_a_service_role_token_is_refused():
    """Right audience, wrong role: a leaked service key must not act as a user."""
    payload = supa.claims() | {"role": "service_role"}

    with pytest.raises(ValueError):
        verify_access_token(supa.sign(payload))


def test_an_anonymous_user_is_refused():
    payload = supa.claims() | {"is_anonymous": True}

    with pytest.raises(ValueError):
        verify_access_token(supa.sign(payload))


def test_a_token_without_a_subject_is_refused():
    payload = supa.claims()
    del payload["sub"]

    with pytest.raises(ValueError):
        verify_access_token(supa.sign(payload))


def test_a_token_without_an_expiry_is_refused():
    payload = supa.claims()
    del payload["exp"]

    with pytest.raises(ValueError):
        verify_access_token(supa.sign(payload))


def test_an_hs256_token_is_refused_even_when_it_names_a_real_key():
    """Algorithm confusion: an HMAC token keyed with public material must never verify."""
    token = jwt.encode(
        supa.claims(),
        "public-knowledge-is-not-a-secret",
        algorithm="HS256",
        headers={"kid": supa.KID},
    )

    with pytest.raises(ValueError):
        verify_access_token(token)


@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c"])
def test_nonsense_is_refused_with_a_value_error(garbage):
    with pytest.raises(ValueError):
        verify_access_token(garbage)


def test_a_token_without_an_email_is_refused():
    """A phone-only user has no address to own a tenant by."""
    payload = supa.claims() | {"email": ""}

    with pytest.raises(ValueError):
        verify_access_token(supa.sign(payload))

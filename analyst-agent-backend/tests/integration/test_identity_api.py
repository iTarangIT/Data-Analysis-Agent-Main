"""Supabase says who is calling; the App DB says which organisation they belong to.

These cover the seam between the two: a verified identity with no account, an existing
account adopted by a verified email, and creating an organisation on first sign-in.
"""

import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import func, select

from tests import supabase_tokens as supa
from tests.integration.accounts import auth, create_account

pytestmark = pytest.mark.integration


def _legacy_user(db, *, email: str, tenant_id: str = "t_legacy", user_id: str = "u_legacy"):
    """An account from before Supabase: no identity linked to it yet."""
    from app.db.models import Tenant, User

    db.add(Tenant(id=tenant_id, name="Legacy Org"))
    db.add(User(id=user_id, tenant_id=tenant_id, email=email))
    db.commit()
    return db.get(User, user_id)


def _tenant_count(db) -> int:
    from app.db.models import Tenant

    return db.execute(select(func.count()).select_from(Tenant)).scalar_one()


class TestMe:
    def test_a_member_sees_their_account(self, client, clean_app_db):
        token = create_account(clean_app_db, "t_me", email="me@example.com")

        r = client.get("/auth/me", headers=auth(token))

        assert r.status_code == 200
        assert (r.json()["email"], r.json()["tenant_id"]) == ("me@example.com", "t_me")

    def test_a_supabase_user_with_no_account_is_told_to_onboard(self, client, clean_app_db):
        r = client.get("/auth/me", headers=auth(supa.mint(email="new@example.com")))

        assert r.status_code == 403
        assert r.json()["code"] == "onboarding_required"

    def test_tenant_routes_also_require_onboarding(self, client, clean_app_db):
        r = client.get("/connections", headers=auth(supa.mint(email="new@example.com")))

        assert r.status_code == 403
        assert r.json()["code"] == "onboarding_required"

    def test_a_token_from_another_signer_is_a_401(self, client, clean_app_db):
        forged = supa.sign(supa.claims(), key=ec.generate_private_key(ec.SECP256R1()))

        assert client.get("/auth/me", headers=auth(forged)).status_code == 401

    def test_a_disabled_account_is_refused_without_being_sent_to_onboarding(
        self, client, clean_app_db
    ):
        from app.db.models import User

        token = create_account(clean_app_db, "t_off", email="off@example.com")
        user = clean_app_db.execute(
            select(User).where(User.email == "off@example.com")
        ).scalar_one()
        user.is_active = False
        clean_app_db.commit()

        r = client.get("/auth/me", headers=auth(token))

        assert r.status_code == 403
        assert r.json().get("code") != "onboarding_required"


class TestAdoptingAnExistingAccount:
    def test_a_verified_email_adopts_the_account_and_keeps_its_tenant(self, client, clean_app_db):
        user = _legacy_user(clean_app_db, email="legacy@example.com")
        sub = str(uuid.uuid4())

        r = client.get("/auth/me", headers=auth(supa.mint(sub=sub, email="Legacy@Example.com")))

        assert r.status_code == 200
        assert (r.json()["id"], r.json()["tenant_id"]) == ("u_legacy", "t_legacy")
        clean_app_db.refresh(user)
        assert user.auth_user_id == sub

    def test_an_unverified_email_adopts_nothing(self, client, clean_app_db):
        """Otherwise anyone who can sign up with an address, unconfirmed, takes over its
        organisation."""
        user = _legacy_user(clean_app_db, email="legacy@example.com")

        r = client.get(
            "/auth/me",
            headers=auth(supa.mint(email="legacy@example.com", email_verified=False)),
        )

        assert r.status_code == 403
        assert r.json()["code"] == "onboarding_required"
        clean_app_db.refresh(user)
        assert user.auth_user_id is None

    def test_an_account_linked_to_someone_else_is_not_taken_over(self, client, clean_app_db):
        from app.db.models import User

        create_account(clean_app_db, "t_owned", email="owned@example.com")
        owner = clean_app_db.execute(
            select(User).where(User.email == "owned@example.com")
        ).scalar_one()
        linked_to = owner.auth_user_id

        r = client.get("/auth/me", headers=auth(supa.mint(email="owned@example.com")))

        assert r.status_code == 403
        clean_app_db.refresh(owner)
        assert owner.auth_user_id == linked_to


class TestProvision:
    def test_it_creates_the_organisation_with_the_caller_as_owner(self, client, clean_app_db):
        headers = auth(supa.mint(email="founder@example.com", name="Fay Founder"))

        r = client.post("/auth/provision", json={"tenant_name": "Acme Logistics"}, headers=headers)

        assert r.status_code == 201, r.text
        body = r.json()
        assert body["tenant_name"] == "Acme Logistics"
        assert (body["email"], body["name"], body["role"]) == (
            "founder@example.com",
            "Fay Founder",
            "owner",
        )
        me = client.get("/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["id"] == body["id"]

    @pytest.mark.parametrize("payload", [{}, {"tenant_name": ""}, {"tenant_name": "   "}])
    def test_the_organisation_needs_a_name(self, client, clean_app_db, payload):
        r = client.post("/auth/provision", json=payload, headers=auth(supa.mint()))

        assert r.status_code == 422
        assert _tenant_count(clean_app_db) == 0

    def test_the_name_is_trimmed(self, client, clean_app_db):
        r = client.post(
            "/auth/provision", json={"tenant_name": "  Acme  "}, headers=auth(supa.mint())
        )

        assert r.json()["tenant_name"] == "Acme"

    def test_a_second_organisation_is_a_conflict(self, client, clean_app_db):
        headers = auth(supa.mint(email="twice@example.com"))
        assert (
            client.post("/auth/provision", json={"tenant_name": "One"}, headers=headers).status_code
            == 201
        )

        r = client.post("/auth/provision", json={"tenant_name": "Two"}, headers=headers)

        assert r.status_code == 409
        assert _tenant_count(clean_app_db) == 1

    def test_an_address_that_already_has_an_account_is_a_conflict(self, client, clean_app_db):
        _legacy_user(clean_app_db, email="taken@example.com")

        r = client.post(
            "/auth/provision",
            json={"tenant_name": "Squatter"},
            headers=auth(supa.mint(email="taken@example.com", email_verified=False)),
        )

        assert r.status_code == 409
        assert _tenant_count(clean_app_db) == 1

    def test_closed_signup_creates_nothing(self, client, clean_app_db, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "allow_open_signup", False)

        r = client.post("/auth/provision", json={"tenant_name": "Acme"}, headers=auth(supa.mint()))

        assert r.status_code == 403
        assert _tenant_count(clean_app_db) == 0

    def test_it_needs_a_token(self, client, clean_app_db):
        assert client.post("/auth/provision", json={"tenant_name": "Acme"}).status_code == 401


class TestTenantIsolation:
    def test_two_founders_get_two_organisations(self, client, clean_app_db):
        a = auth(supa.mint(email="a@example.com"))
        b = auth(supa.mint(email="b@example.com"))
        client.post("/auth/provision", json={"tenant_name": "A"}, headers=a)
        client.post("/auth/provision", json={"tenant_name": "B"}, headers=b)

        a_tenant = client.get("/auth/me", headers=a).json()["tenant_id"]
        b_tenant = client.get("/auth/me", headers=b).json()["tenant_id"]

        assert a_tenant != b_tenant

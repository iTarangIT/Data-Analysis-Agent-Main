import time

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration

PASSWORD = "a-long-enough-password"


def _register(client, email="owner@example.com", password=PASSWORD, **extra):
    return client.post("/auth/register", json={"email": email, "password": password, **extra})


class TestRegister:
    def test_creates_an_account_and_returns_a_token_pair(self, client, clean_app_db):
        r = _register(client, tenant_name="Acme")
        assert r.status_code == 201
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 900
        assert body["access_token"] and body["refresh_token"]
        assert body["user"]["email"] == "owner@example.com"
        assert body["user"]["tenant_name"] == "Acme"

    def test_the_first_user_owns_the_tenant_they_created(self, client, clean_app_db):
        assert _register(client).json()["user"]["role"] == "owner"

    def test_the_tenant_falls_back_to_the_email_when_unnamed(self, client, clean_app_db):
        assert _register(client).json()["user"]["tenant_name"] == "owner@example.com"

    def test_the_response_never_carries_the_password(self, client, clean_app_db):
        # Greps the raw body, so a nested or renamed field cannot slip through.
        r = _register(client)
        assert PASSWORD not in r.text
        assert "password_hash" not in r.text
        assert "argon2" not in r.text

    def test_the_password_is_hashed_at_rest(self, client, clean_app_db):
        from app.db.models import User

        _register(client)
        user = clean_app_db.scalar(select(User))
        assert user.password_hash != PASSWORD
        assert user.password_hash.startswith("$argon2id$")

    def test_a_duplicate_email_is_rejected(self, client, clean_app_db):
        _register(client)
        r = _register(client)
        assert r.status_code == 409
        assert r.json() == {"error": "an account with that email already exists"}

    def test_duplicate_detection_ignores_case(self, client, clean_app_db):
        from app.db.models import User

        _register(client, email="Owner@Example.com")
        assert _register(client, email="OWNER@EXAMPLE.COM").status_code == 409
        assert len(clean_app_db.scalars(select(User)).all()) == 1

    def test_each_signup_gets_its_own_tenant(self, client, clean_app_db):
        a = _register(client, email="a@example.com").json()
        b = _register(client, email="b@example.com").json()
        assert a["user"]["tenant_id"] != b["user"]["tenant_id"]

    @pytest.mark.parametrize(
        "body",
        [
            {"email": "not-an-email", "password": PASSWORD},
            {"email": "a@example.com", "password": "short"},
            {"email": "a@example.com", "password": "x" * 129},
            {"email": "a@example.com"},
        ],
    )
    def test_a_bad_body_is_rejected(self, client, clean_app_db, body):
        r = client.post("/auth/register", json=body)
        assert r.status_code == 422
        assert "detail" in r.json()  # the other error envelope, which clients must also parse

    def test_signups_can_be_closed(self, client, clean_app_db, monkeypatch):
        from app.config import get_settings

        s = get_settings()
        monkeypatch.setattr(s, "allow_open_signup", False)
        r = _register(client)
        assert r.status_code == 403
        assert r.json() == {"error": "signups are closed"}


class TestLogin:
    def test_returns_a_token_pair(self, client, clean_app_db):
        _register(client)
        r = client.post("/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
        assert r.status_code == 200
        assert r.json()["access_token"] and r.json()["refresh_token"]

    def test_email_is_case_insensitive(self, client, clean_app_db):
        _register(client, email="owner@example.com")
        r = client.post("/auth/login", json={"email": "OWNER@Example.com", "password": PASSWORD})
        assert r.status_code == 200

    def test_a_wrong_password_is_rejected(self, client, clean_app_db):
        _register(client)
        r = client.post(
            "/auth/login", json={"email": "owner@example.com", "password": "wrong-password"}
        )
        assert r.status_code == 401

    def test_an_unknown_email_is_indistinguishable_from_a_wrong_password(
        self, client, clean_app_db
    ):
        # Byte-identical replies, or the endpoint tells an attacker which addresses exist.
        _register(client)
        unknown = client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
        )
        wrong = client.post(
            "/auth/login", json={"email": "owner@example.com", "password": "wrong-password"}
        )
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.text == wrong.text

    def test_a_deactivated_account_cannot_sign_in(self, client, clean_app_db):
        from app.db.models import User

        _register(client)
        user = clean_app_db.scalar(select(User))
        user.is_active = False
        clean_app_db.commit()

        r = client.post("/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
        assert r.status_code == 401
        # Same message as a wrong password, so disabling an account does not announce itself.
        assert r.json() == {"error": "invalid email or password"}

    def test_signing_in_twice_leaves_both_sessions_alive(self, client, clean_app_db):
        # A column on `users` would hold one token, so the phone would sign the laptop out.
        _register(client)
        first = client.post(
            "/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
        ).json()["refresh_token"]
        second = client.post(
            "/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
        ).json()["refresh_token"]

        assert client.post("/auth/refresh", json={"refresh_token": first}).status_code == 200
        assert client.post("/auth/refresh", json={"refresh_token": second}).status_code == 200


class TestRefresh:
    def test_rotates_the_pair(self, client, clean_app_db):
        old = _register(client).json()["refresh_token"]
        r = client.post("/auth/refresh", json={"refresh_token": old})
        assert r.status_code == 200
        assert r.json()["refresh_token"] != old

    def test_needs_no_bearer(self, client, clean_app_db):
        # The refresh token is the credential, and the access token it replaces has expired.
        old = _register(client).json()["refresh_token"]
        assert client.post("/auth/refresh", json={"refresh_token": old}).status_code == 200

    def test_an_unknown_token_is_rejected(self, client, clean_app_db):
        r = client.post("/auth/refresh", json={"refresh_token": "not-a-real-token"})
        assert r.status_code == 401
        assert r.json() == {"error": "invalid or expired refresh token"}

    def test_an_expired_token_is_rejected(self, client, clean_app_db):
        from datetime import UTC, datetime, timedelta

        from app.db.models import RefreshToken

        raw = _register(client).json()["refresh_token"]
        row = clean_app_db.scalar(select(RefreshToken))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        clean_app_db.commit()

        assert client.post("/auth/refresh", json={"refresh_token": raw}).status_code == 401

    def test_reuse_after_the_grace_window_kills_the_whole_family(
        self, client, clean_app_db, monkeypatch
    ):
        """The single most important test here.

        A rotated token coming back late means it was captured, so every token descended from
        that sign-in dies, not merely the one replayed.
        """
        from app.config import get_settings
        from app.db.models import RefreshToken

        monkeypatch.setattr(get_settings(), "refresh_reuse_grace_seconds", 0)

        first = _register(client).json()["refresh_token"]
        second = client.post("/auth/refresh", json={"refresh_token": first}).json()["refresh_token"]
        time.sleep(0.01)

        assert client.post("/auth/refresh", json={"refresh_token": first}).status_code == 401
        # And the token that was legitimately issued is dead too.
        assert client.post("/auth/refresh", json={"refresh_token": second}).status_code == 401

        rows = clean_app_db.scalars(select(RefreshToken)).all()
        assert rows and all(r.revoked_at is not None for r in rows)

    def test_a_race_inside_the_grace_window_spares_the_family(self, client, clean_app_db):
        """Two requests sharing a session present the same token at once. The loser is not an
        attacker, and killing the session every fifteen minutes would be the real bug."""
        first = _register(client).json()["refresh_token"]
        second = client.post("/auth/refresh", json={"refresh_token": first}).json()["refresh_token"]

        assert client.post("/auth/refresh", json={"refresh_token": first}).status_code == 401
        # The winner's token still works, which is what makes this survivable.
        assert client.post("/auth/refresh", json={"refresh_token": second}).status_code == 200

    def test_a_deactivated_user_cannot_refresh(self, client, clean_app_db):
        from app.db.models import User

        raw = _register(client).json()["refresh_token"]
        user = clean_app_db.scalar(select(User))
        user.is_active = False
        clean_app_db.commit()

        assert client.post("/auth/refresh", json={"refresh_token": raw}).status_code == 401


class TestLogout:
    def test_revokes_the_refresh_token(self, client, clean_app_db):
        raw = _register(client).json()["refresh_token"]
        assert client.post("/auth/logout", json={"refresh_token": raw}).status_code == 204
        assert client.post("/auth/refresh", json={"refresh_token": raw}).status_code == 401

    def test_does_not_revoke_the_access_token(self, client, clean_app_db):
        """Deliberate, and worth asserting so it is not later filed as a bug.

        An access token is stateless and cannot be recalled. Fifteen minutes is the whole
        reason its life is short.
        """
        body = _register(client).json()
        client.post("/auth/logout", json={"refresh_token": body["refresh_token"]})
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert r.status_code == 200

    def test_an_unknown_token_still_returns_204(self, client, clean_app_db):
        # Idempotent, and saying otherwise would reveal whether a token was ever real.
        r = client.post("/auth/logout", json={"refresh_token": "never-existed"})
        assert r.status_code == 204

    def test_logging_out_twice_is_not_an_error(self, client, clean_app_db):
        raw = _register(client).json()["refresh_token"]
        client.post("/auth/logout", json={"refresh_token": raw})
        assert client.post("/auth/logout", json={"refresh_token": raw}).status_code == 204

    def test_all_devices_revokes_every_session(self, client, clean_app_db):
        _register(client)
        a = client.post(
            "/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
        ).json()["refresh_token"]
        b = client.post(
            "/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
        ).json()["refresh_token"]

        assert (
            client.post("/auth/logout", json={"refresh_token": a, "all_devices": True}).status_code
            == 204
        )
        assert client.post("/auth/refresh", json={"refresh_token": a}).status_code == 401
        assert client.post("/auth/refresh", json={"refresh_token": b}).status_code == 401


class TestMe:
    def test_returns_the_signed_in_user(self, client, clean_app_db):
        body = _register(client, tenant_name="Acme").json()
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert r.status_code == 200
        assert r.json()["email"] == "owner@example.com"
        assert r.json()["tenant_name"] == "Acme"
        assert r.json()["plan"] == "free"

    def test_carries_no_password_field(self, client, clean_app_db):
        body = _register(client).json()
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert PASSWORD not in r.text
        assert "password" not in r.text

    def test_requires_a_token(self, client, clean_app_db):
        r = client.get("/auth/me")
        assert r.status_code == 401
        assert r.json() == {"detail": "missing bearer token"}

    def test_a_hand_minted_token_gets_a_clean_404(self, client, clean_app_db, token):
        """The eval harness and every existing fixture sign tokens for subjects with no row.

        It must stay a 404 rather than becoming a 500, or the harness breaks.
        """
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404
        assert r.json() == {"error": "user not found"}

    def test_a_refresh_token_is_not_accepted_as_a_bearer(self, client, clean_app_db):
        """Enforces the opaque-token decision.

        `decode_token` accepts any correctly signed token carrying tenant_id and sub, so if a
        refresh token were ever "simplified" into a JWT it would become a thirty-day bearer
        for the whole API. This test is what fails when someone tries.
        """
        raw = _register(client).json()["refresh_token"]
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {raw}"})
        assert r.status_code == 401


class TestTenantIsolation:
    def test_neither_tenant_sees_the_other(self, client, clean_app_db, demo_dsn):
        a = _register(client, email="a@example.com").json()
        b = _register(client, email="b@example.com").json()
        a_headers = {"Authorization": f"Bearer {a['access_token']}"}
        b_headers = {"Authorization": f"Bearer {b['access_token']}"}

        client.post(
            "/connections",
            headers=a_headers,
            json={"name": "a-db", "kind": "postgres", "secret": {"dsn": demo_dsn}},
        )
        assert client.get("/connections", headers=a_headers).json() != []
        assert client.get("/connections", headers=b_headers).json() == []

    def test_the_body_cannot_override_the_tenant_from_the_token(
        self, client, clean_app_db, demo_dsn
    ):
        """Hard rule 3: tenant_id comes only from the JWT, never from a body or a query."""
        from app.db.models import Connection

        a = _register(client, email="a@example.com").json()
        b = _register(client, email="b@example.com").json()

        client.post(
            "/connections",
            headers={"Authorization": f"Bearer {a['access_token']}"},
            json={
                "name": "a-db",
                "kind": "postgres",
                "secret": {"dsn": demo_dsn},
                "tenant_id": b["user"]["tenant_id"],
            },
        )
        conn = clean_app_db.scalar(select(Connection))
        assert conn is not None
        assert conn.tenant_id == a["user"]["tenant_id"]

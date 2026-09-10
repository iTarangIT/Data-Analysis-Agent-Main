import pytest

pytestmark = pytest.mark.integration


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_listing_requires_a_token(client):
    assert client.get("/connections").status_code == 401


def test_create_then_list(client, token, demo_dsn, clean_app_db):
    r = client.post(
        "/connections",
        headers=_auth(token),
        json={"name": "demo", "kind": "postgres", "secret": {"dsn": demo_dsn}},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "demo" and body["has_schema_cache"] is False

    listed = client.get("/connections", headers=_auth(token)).json()
    assert [c["id"] for c in listed] == [body["id"]]


def test_the_response_never_carries_the_credential(client, token, demo_dsn, clean_app_db):
    r = client.post(
        "/connections",
        headers=_auth(token),
        json={"name": "demo", "kind": "postgres", "secret": {"dsn": demo_dsn}},
    )
    raw = r.text
    for leaked in ("secret", "dsn", "password", "analyst_ro", "ro@localhost"):
        assert leaked not in raw, f"response leaked {leaked!r}"


def test_the_credential_is_encrypted_at_rest(client, token, demo_dsn, clean_app_db):
    client.post(
        "/connections",
        headers=_auth(token),
        json={"name": "demo", "kind": "postgres", "secret": {"dsn": demo_dsn}},
    )
    from app.db.models import Connection

    stored = clean_app_db.query(Connection).one()
    assert "postgresql" not in stored.secret_enc and "analyst_ro" not in stored.secret_enc

    from app.security import vault

    assert vault.decrypt(stored.secret_enc) == {"dsn": demo_dsn}


def test_another_tenant_cannot_see_it(client, token, other_token, demo_dsn, clean_app_db):
    client.post(
        "/connections",
        headers=_auth(token),
        json={"name": "demo", "kind": "postgres", "secret": {"dsn": demo_dsn}},
    )
    assert client.get("/connections", headers=_auth(other_token)).json() == []


def test_an_unreachable_database_is_rejected_before_it_is_stored(client, token, clean_app_db):
    r = client.post(
        "/connections",
        headers=_auth(token),
        json={
            "name": "broken",
            "kind": "postgres",
            "secret": {"dsn": "postgresql+psycopg://nobody:nope@localhost:5432/nosuchdb"},
        },
    )
    assert r.status_code == 400
    assert "nope" not in r.text, "the rejection leaked the password"
    assert "nobody" not in r.text, "the rejection leaked the username"

    from app.db.models import Connection

    assert clean_app_db.query(Connection).count() == 0

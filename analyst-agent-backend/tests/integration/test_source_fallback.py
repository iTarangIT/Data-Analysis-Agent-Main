"""A live question whose dashboard cannot be read at all.

This is the half of the fallback the middleware cannot reach. When the dashboard's schema
cannot be introspected the agent has not been built yet, so `prepare_run` has to switch
sources itself. It used to refuse here, which left the customer with nothing when the
database could have answered from recorded data.
"""

import pytest

from app.api.schemas import RunCreate
from app.services import runs as svc
from app.workers.web_session import DashboardUnavailable

pytestmark = pytest.mark.integration


@pytest.fixture
def both_sources(client, token, demo_dsn, clean_app_db):
    def _auth():
        return {"Authorization": f"Bearer {token}"}

    db = client.post(
        "/connections",
        headers=_auth(),
        json={"name": "IoT database", "kind": "postgres", "secret": {"dsn": demo_dsn}},
    )
    assert db.status_code == 201
    web = client.post(
        "/connections",
        headers=_auth(),
        json={
            "name": "Live dashboard",
            "kind": "web",
            "secret": {"url": "https://example.invalid", "username": "u", "password": "p"},
        },
    )
    assert web.status_code == 201
    return db.json()["id"], web.json()["id"]


@pytest.fixture
def ctx(token):
    from app.security.auth import decode_token

    return decode_token(token)


async def test_an_unreadable_dashboard_falls_back_to_the_database(both_sources, ctx, monkeypatch):
    db_id, web_id = both_sources
    from app.db.session import SessionLocal

    def refuse(self, *a, **k):
        raise DashboardUnavailable("the dashboard did not accept those credentials")

    monkeypatch.setattr("app.connectors.web.WebConnector.describe_schema", refuse)

    session = SessionLocal()
    try:
        prepared = await svc.prepare_run(
            session,
            ctx,
            RunCreate(connection_id=web_id, thread_id="fb", question="what is the charge now"),
        )
    finally:
        session.close()

    assert prepared.run.connection_id == db_id
    assert prepared.fell_back is True
    # Nothing left to fall back to, so the middleware must not also be armed.
    assert prepared.backup is None


async def test_it_still_refuses_when_there_is_nothing_to_fall_back_to(
    client, token, ctx, clean_app_db, monkeypatch
):
    r = client.post(
        "/connections",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Live dashboard",
            "kind": "web",
            "secret": {"url": "https://example.invalid", "username": "u", "password": "p"},
        },
    )
    assert r.status_code == 201

    def refuse(self, *a, **k):
        raise DashboardUnavailable("the dashboard did not accept those credentials")

    monkeypatch.setattr("app.connectors.web.WebConnector.describe_schema", refuse)

    from app.db.session import SessionLocal
    from app.services.errors import DomainError

    session = SessionLocal()
    try:
        with pytest.raises(DomainError, match="could not read the live dashboard"):
            await svc.prepare_run(
                session,
                ctx,
                RunCreate(connection_id=r.json()["id"], thread_id="fb", question="charge now"),
            )
    finally:
        session.close()

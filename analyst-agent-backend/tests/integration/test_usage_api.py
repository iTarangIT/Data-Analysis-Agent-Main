"""`GET /usage`. The aggregate lives here because the agent owns the `runs` table; the Next.js
route proxies this rather than reaching into the App DB itself."""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import Run

pytestmark = pytest.mark.integration


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def connection_id(client, token, demo_dsn, clean_app_db) -> str:
    r = client.post(
        "/connections",
        headers=_auth(token),
        json={"name": "demo", "kind": "postgres", "secret": {"dsn": demo_dsn}},
    )
    return r.json()["id"]


def _seed(db, connection_id, tenant_id="t_test", **kw):
    db.add(
        Run(
            tenant_id=tenant_id,
            connection_id=connection_id,
            thread_id="u",
            question="seeded",
            status=kw.get("status", "done"),
            created_at=kw.get("created_at", datetime.now(UTC)),
            prompt_tokens=kw.get("prompt_tokens", 100),
            completion_tokens=kw.get("completion_tokens", 20),
            rows_returned=kw.get("rows_returned", 3),
        )
    )
    db.commit()


class TestContract:
    def test_it_requires_a_token(self, client):
        assert client.get("/usage").status_code == 401

    def test_the_window_is_bounded(self, client, token, clean_app_db):
        assert client.get("/usage?days=0", headers=_auth(token)).status_code == 422
        assert client.get("/usage?days=91", headers=_auth(token)).status_code == 422


class TestAggregates:
    def test_it_totals_this_tenants_runs(self, client, token, connection_id, clean_app_db):
        _seed(clean_app_db, connection_id)
        _seed(clean_app_db, connection_id, status="error")

        body = client.get("/usage", headers=_auth(token)).json()

        assert body["runs_last_24h"] == 2
        assert body["tokens_last_24h"] == 240
        assert len(body["days"]) == 1
        assert body["days"][0]["runs"] == 2
        assert body["days"][0]["errors"] == 1
        assert body["days"][0]["prompt_tokens"] == 200

    def test_another_tenants_runs_are_excluded(
        self, client, token, other_token, connection_id, clean_app_db
    ):
        from app.services import connections as conn_svc

        conn_svc.ensure_tenant(clean_app_db, "t_other")
        _seed(clean_app_db, connection_id)
        _seed(clean_app_db, connection_id, tenant_id="t_other", prompt_tokens=9999)

        body = client.get("/usage", headers=_auth(token)).json()

        assert body["tokens_last_24h"] == 120
        assert client.get("/usage", headers=_auth(other_token)).json()["tokens_last_24h"] == 10019

    def test_runs_outside_the_window_are_excluded(self, client, token, connection_id, clean_app_db):
        _seed(clean_app_db, connection_id, created_at=datetime.now(UTC) - timedelta(days=40))

        body = client.get("/usage?days=7", headers=_auth(token)).json()

        assert body["days"] == []
        assert body["runs_last_24h"] == 0

    def test_the_rolling_window_is_reported_beside_the_calendar_days(
        self, client, token, connection_id, clean_app_db
    ):
        """The budget is enforced over a rolling 24 hours. Without this field a tenant getting
        429s could see a calendar day reading zero just after midnight."""
        _seed(clean_app_db, connection_id, created_at=datetime.now(UTC) - timedelta(hours=6))

        body = client.get("/usage", headers=_auth(token)).json()

        assert body["tokens_last_24h"] == 120
        assert body["daily_token_budget"] > 0

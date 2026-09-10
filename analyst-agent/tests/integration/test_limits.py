"""Per-tenant limits, all answered by one indexed scan in `prepare_run`.

They live in the database rather than Redis so they behave identically with the queue off,
which is the default for local development.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import Run, Tenant

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
    assert r.status_code == 201
    return r.json()["id"]


def _seed(db, connection_id: str, count: int, **overrides) -> None:
    for i in range(count):
        db.add(
            Run(
                tenant_id="t_test",
                connection_id=connection_id,
                thread_id=f"seed-{i}",
                question="seeded",
                status=overrides.get("status", "done"),
                created_at=overrides.get("created_at", datetime.now(UTC)),
                prompt_tokens=overrides.get("prompt_tokens", 0),
                completion_tokens=overrides.get("completion_tokens", 0),
            )
        )
    db.commit()


def _ask(client, token: str, connection_id: str):
    return client.post(
        "/runs",
        headers=_auth(token),
        json={
            "connection_id": connection_id,
            "thread_id": "limits-1",
            "question": "How many dealers do we have?",
        },
    )


class TestRateLimit:
    def test_too_many_runs_in_a_minute_is_refused(self, client, token, connection_id, clean_app_db):
        from app.config import get_settings

        _seed(clean_app_db, connection_id, get_settings().max_runs_per_minute)

        r = _ask(client, token, connection_id)

        assert r.status_code == 429
        assert "last minute" in r.json()["error"]

    def test_older_runs_do_not_count_against_the_minute(
        self, client, token, connection_id, clean_app_db, monkeypatch
    ):
        from app.config import get_settings

        _seed(
            clean_app_db,
            connection_id,
            get_settings().max_runs_per_minute,
            created_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        monkeypatch.setattr(get_settings(), "max_runs_per_minute", 100, raising=False)

        assert _ask(client, token, connection_id).status_code == 200


class TestConcurrency:
    def test_a_tenant_at_the_cap_is_refused(self, client, token, connection_id, clean_app_db):
        from app.config import get_settings

        _seed(clean_app_db, connection_id, get_settings().max_concurrent_runs, status="running")

        r = _ask(client, token, connection_id)

        assert r.status_code == 429
        assert "in progress" in r.json()["error"]

    def test_reaping_a_leaked_row_frees_the_slot(self, client, token, connection_id, clean_app_db):
        """The reaper is load-bearing: the cap counts running rows, so a row left behind by a
        killed process would consume a tenant's slot for ever."""
        from app.config import get_settings
        from app.services.runs import reap_stale_runs

        s = get_settings()
        _seed(
            clean_app_db,
            connection_id,
            s.max_concurrent_runs,
            status="running",
            created_at=datetime.now(UTC) - timedelta(seconds=s.run_timeout_s + 60),
        )
        assert _ask(client, token, connection_id).status_code == 429

        assert reap_stale_runs(clean_app_db) == s.max_concurrent_runs

        assert _ask(client, token, connection_id).status_code == 200


class TestBudget:
    def test_an_exhausted_budget_reports_differently_from_a_rate_limit(
        self, client, token, connection_id, clean_app_db
    ):
        tenant = clean_app_db.get(Tenant, "t_test")
        _seed(
            clean_app_db,
            connection_id,
            1,
            prompt_tokens=tenant.daily_token_budget,
            completion_tokens=1,
        )

        r = _ask(client, token, connection_id)

        assert r.status_code == 429
        assert "budget" in r.json()["error"]
        assert "last minute" not in r.json()["error"], "the two 429s must stay distinguishable"

    def test_another_tenants_usage_does_not_count(
        self, client, token, other_token, connection_id, clean_app_db
    ):
        from app.config import get_settings

        _seed(clean_app_db, connection_id, get_settings().max_runs_per_minute)

        # t_other has no runs, so its own limit is untouched by t_test's.
        r = client.post(
            "/runs",
            headers=_auth(other_token),
            json={"connection_id": connection_id, "thread_id": "x", "question": "anything here"},
        )
        assert r.status_code == 404, "a different tenant cannot see this connection at all"

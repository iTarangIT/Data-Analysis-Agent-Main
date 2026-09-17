"""Contract checks that stop before the database. The streaming path is covered by
tests/integration/test_runs_api.py."""

import pytest


def _body(**over) -> dict:
    return {"connection_id": "c1", "thread_id": "t1", "question": "how many dealers"} | over


def test_rejects_a_request_without_a_token(client):
    assert client.post("/runs", json=_body()).status_code == 401


def test_rejects_a_malformed_token(client):
    r = client.post("/runs", json=_body(), headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


@pytest.fixture
def signed_in(client):
    """Stands in for an onboarded member, since resolving a real one reads the App DB."""
    from app.api.deps import current_tenant
    from app.security.auth import TenantContext

    client.app.dependency_overrides[current_tenant] = lambda: TenantContext("t_test", "u_test")
    yield
    client.app.dependency_overrides.pop(current_tenant)


@pytest.mark.parametrize("bad", [{"question": "hi"}, {"thread_id": ""}, {"connection_id": 7}])
def test_rejects_an_invalid_body_before_touching_the_database(client, signed_in, bad):
    r = client.post("/runs", json=_body(**bad), headers={"Authorization": "Bearer ignored"})
    assert r.status_code == 422

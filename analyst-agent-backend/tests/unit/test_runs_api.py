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


@pytest.mark.parametrize("bad", [{"question": "hi"}, {"thread_id": ""}, {"connection_id": 7}])
def test_rejects_an_invalid_body_before_touching_the_database(client, token, bad):
    r = client.post("/runs", json=_body(**bad), headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 422

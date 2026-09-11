"""`WebConnector` against a stubbed session manager, so no browser is needed."""

import pytest

from app.connectors import web
from app.connectors.web import WebConnector

SECRET = {"url": "https://dash.example", "username": "u", "password": "p"}
PAYLOAD = [
    {"vehicleno": "KA01", "soc": 82, "updated": "2026-09-10"},
    {"vehicleno": "KA02", "soc": 61},
]


@pytest.fixture
def fetches(monkeypatch):
    calls = []

    def fake(tenant_id, connection_id, secret, data_url_match):
        calls.append((tenant_id, connection_id, data_url_match))
        return PAYLOAD

    monkeypatch.setattr(web, "fetch_dashboard_json", fake)
    return calls


@pytest.fixture
def connector(fetches):
    return WebConnector("t_a", "c1", SECRET)


class TestSchema:
    def test_it_describes_one_table_named_dashboard(self, connector):
        schema = connector.describe_schema(sample_rows=0)

        assert [t["name"] for t in schema["tables"]] == ["dashboard"]

    def test_columns_are_the_sorted_union_of_every_row(self, connector):
        cols = [c["name"] for c in connector.describe_schema(sample_rows=0)["tables"][0]["columns"]]

        assert cols == ["soc", "updated", "vehicleno"]

    def test_types_come_from_the_first_non_null_value(self, connector):
        columns = connector.describe_schema(sample_rows=0)["tables"][0]["columns"]

        assert {c["name"]: c["type"] for c in columns} == {
            "soc": "int",
            "updated": "str",
            "vehicleno": "str",
        }

    def test_sample_rows_are_governed_by_the_existing_setting(self, connector):
        assert connector.describe_schema(sample_rows=0)["tables"][0]["sample"] == []
        assert len(connector.describe_schema(sample_rows=1)["tables"][0]["sample"]) == 1


class TestRows:
    def test_a_missing_key_becomes_none_rather_than_shifting_the_row(self, connector):
        cols, rows = connector.fetch_rows(10)

        assert cols == ["soc", "updated", "vehicleno"]
        assert rows == [(82, "2026-09-10", "KA01"), (61, None, "KA02")]

    def test_rows_are_capped(self, connector):
        _, rows = connector.fetch_rows(1)

        assert len(rows) == 1


class TestOneFetchPerRun:
    def test_the_schema_and_the_rows_share_one_browser_session(self, connector, fetches):
        connector.describe_schema(sample_rows=0)
        connector.fetch_rows(10)

        assert len(fetches) == 1, "a cold run must not sign in twice"


class TestConfiguration:
    def test_the_connection_can_override_the_default_match(self, fetches):
        WebConnector("t_a", "c1", {**SECRET, "data_url_match": "/v2/report"}).fetch_rows(1)

        assert fetches[0][2] == "/v2/report"

    def test_it_falls_back_to_the_setting(self, connector, fetches):
        from app.config import get_settings

        connector.fetch_rows(1)

        assert fetches[0][2] == get_settings().web_data_url_match

    def test_the_tenant_reaches_the_session_manager(self, connector, fetches):
        connector.fetch_rows(1)

        assert fetches[0][:2] == ("t_a", "c1")

    def test_it_is_not_a_sql_connector(self, connector):
        assert connector.kind == "web"
        assert not hasattr(connector, "run_select"), "a dashboard has no query language"

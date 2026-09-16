"""The connector is a `SqlConnector` whose four methods happen to be MCP calls.

What matters is that it is a faithful stand-in for the in-process connector it replaced: the
same arguments in, the same shapes out. The MCP server itself is exercised in the integration
suite; here the transport is stubbed so the mapping can be checked without one running.
"""

from types import SimpleNamespace

import pytest

from app import mcp_client
from app.connectors.mcp import McpConnector


@pytest.fixture
def calls(monkeypatch):
    """Record what the connector asks for, and reply with whatever the test queued."""
    recorded: list[tuple] = []
    replies: dict[str, object] = {}

    def fake_call(tenant_id, connection_id, tool, args):
        recorded.append((tenant_id, connection_id, tool, args))
        return replies[tool]

    monkeypatch.setattr(mcp_client, "call", fake_call)
    return SimpleNamespace(recorded=recorded, replies=replies)


@pytest.fixture
def connector():
    return McpConnector("t_a", "c1")


def test_every_call_names_the_tenant_and_connection_it_was_built_for(connector, calls):
    calls.replies["list_tables"] = ["dealers"]

    connector.list_tables()

    tenant_id, connection_id, tool, args = calls.recorded[0]
    assert (tenant_id, connection_id, tool, args) == ("t_a", "c1", "list_tables", {})


def test_read_tables_comes_back_as_table_definitions(connector, calls):
    calls.replies["read_tables"] = [
        {
            "name": "telemetry",
            "columns": [{"name": "id", "type": "integer", "nullable": False}],
            "primary_key": ["id"],
            "foreign_keys": [
                {"columns": ["battery_id"], "ref_table": "batteries", "ref_columns": ["id"]}
            ],
        }
    ]

    definitions = connector.read_tables(["telemetry"])

    assert [d.name for d in definitions] == ["telemetry"]
    assert definitions[0].primary_key == ["id"]
    assert definitions[0].foreign_keys[0].ref_table == "batteries"
    assert calls.recorded[0][3] == {"names": ["telemetry"]}


def test_run_select_returns_columns_and_rows_as_tuples(connector, calls):
    """The same `(cols, rows)` pair the in-process connector returned, so `app.agent.tools` -
    which counts the rows it asked one beyond for - needs no change."""
    calls.replies["run_select"] = {
        "sql": "SELECT n FROM telemetry LIMIT 500",
        "columns": ["n"],
        "rows": [[1], [2]],
        "error": None,
    }

    cols, rows = connector.run_select("SELECT n FROM telemetry", 501)

    assert cols == ["n"]
    assert rows == [(1,), (2,)]
    assert calls.recorded[0][3] == {"sql": "SELECT n FROM telemetry", "max_rows": 501}


def test_a_rejection_by_the_server_is_raised_not_returned(connector, calls):
    """The server guards independently. Reaching a rejection means the two guards disagreed,
    which is a fault worth surfacing rather than an empty result worth rendering."""
    calls.replies["run_select"] = {"columns": [], "rows": [], "error": "tables not allowed: ['x']"}

    with pytest.raises(RuntimeError, match="tables not allowed"):
        connector.run_select("SELECT * FROM x", 501)


def test_table_stats_passes_the_names_through(connector, calls):
    calls.replies["table_stats"] = {"telemetry": {"rows": "few"}}

    assert connector.table_stats(["telemetry"]) == {"telemetry": {"rows": "few"}}
    assert calls.recorded[0][3] == {"names": ["telemetry"]}


class TestPayload:
    """Structured content is always a JSON object, so a tool returning a list or a scalar comes
    back wrapped. Unwrapping the wrong one would hand the connector a dict where it wants rows."""

    def test_a_wrapped_value_is_unwrapped(self):
        result = SimpleNamespace(isError=False, structuredContent={"result": ["dealers"]})

        assert mcp_client._payload(result) == ["dealers"]

    def test_an_object_is_returned_as_it_stands(self):
        content = {"columns": ["n"], "rows": [[1]], "error": None}
        result = SimpleNamespace(isError=False, structuredContent=content)

        assert mcp_client._payload(result) == content

    def test_an_object_that_merely_has_a_result_key_is_not_unwrapped(self):
        content = {"result": 1, "error": None}
        result = SimpleNamespace(isError=False, structuredContent=content)

        assert mcp_client._payload(result) == content

    def test_an_error_becomes_an_exception_carrying_the_server_text(self):
        from mcp.types import TextContent

        result = SimpleNamespace(
            isError=True,
            structuredContent=None,
            content=[TextContent(type="text", text="connection not found")],
        )

        with pytest.raises(RuntimeError, match="connection not found"):
            mcp_client._payload(result)

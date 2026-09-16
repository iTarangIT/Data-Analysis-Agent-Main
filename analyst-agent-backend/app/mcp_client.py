"""Calling the database MCP server.

Every call mints its own short-lived token naming one tenant and one connection, so a call can
only ever reach the database it was minted for. There is no long-lived session to reuse: the
server is stateless by configuration, and a token that lived longer than a call would be worth
stealing.

`call` is synchronous because every caller is. The connector protocol is sync, the table routes
are sync `def` (FastAPI runs those in its threadpool) and a run reaches the customer's database
through `asyncio.to_thread`. None of those threads has a running event loop, which is what makes
`asyncio.run` here correct rather than merely convenient.
"""

import asyncio
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.types import TextContent

from app.config import get_settings
from app.mcp_auth import mint_mcp_token

REQUIRED_TOOLS = {"list_tables", "read_tables", "table_stats", "run_select"}
SERVER_NAME = "database"


def _client(token: str) -> MultiServerMCPClient:
    settings = get_settings()
    return MultiServerMCPClient(
        {
            SERVER_NAME: {
                "transport": "http",
                "url": str(settings.database_mcp_url),
                "headers": {"Authorization": f"Bearer {token}"},
                "timeout": settings.mcp_request_timeout_s,
            }
        }
    )


def _error_text(result: Any) -> str:
    parts = [block.text for block in result.content if isinstance(block, TextContent)]
    return "\n".join(parts) or "database MCP call failed"


def _payload(result: Any) -> Any:
    if result.isError:
        raise RuntimeError(_error_text(result))
    data = result.structuredContent
    # A tool returning something that is not an object comes back wrapped, because structured
    # content is always a JSON object.
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data


async def _call(tenant_id: str, connection_id: str, tool: str, args: dict[str, Any]) -> Any:
    client = _client(mint_mcp_token(tenant_id=tenant_id, connection_id=connection_id))
    async with client.session(SERVER_NAME) as session:
        return _payload(await session.call_tool(tool, args))


def call(tenant_id: str, connection_id: str, tool: str, args: dict[str, Any]) -> Any:
    return asyncio.run(_call(tenant_id, connection_id, tool, args))


async def probe_mcp() -> None:
    """Check at boot that the server is up and speaks the contract we compiled against.

    The token carries no tenant or connection, so this never reaches a customer's database: it
    only lists what the server offers.
    """
    client = _client(mint_mcp_token())
    async with client.session(SERVER_NAME) as session:
        offered = {tool.name for tool in (await session.list_tools()).tools}
    missing = REQUIRED_TOOLS - offered
    if missing:
        raise RuntimeError(f"database MCP server is missing tools: {sorted(missing)}")

from datetime import date
from typing import Any

from langchain.agents import create_agent

from app.agent import fallback
from app.agent.prompts import AGENT_SYSTEM, SQL_CAPABILITY, WEB_CAPABILITY
from app.agent.tools import make_query_tool, tools_for
from app.config import get_settings
from app.connectors.base import Connector
from app.llm import get_llm


def recursion_limit() -> int:
    """Bound the tool-calling loop, so a confused model cannot spend a tenant's budget.

    One tool call is a model step plus a tool step, and one final model step writes the
    answer.
    """
    return 2 * get_settings().max_tool_calls + 1


def build_agent(
    connector: Connector,
    schema: dict[str, Any],
    checkpointer=None,
    backup=None,
    fell_back: bool = False,
):
    """Build the harness for one source. `app/agent/router.py` chose which source that is.

    The capability block is chosen by kind rather than describing every source at once: a
    connection has one kind, so telling a dashboard tenant how to write SQL would only invite
    the model to claim it had.

    `backup` is the tenant's database, passed only for a dashboard run. It is not a second
    tool: it is a tool the middleware adds if and when the dashboard comes back empty. See
    `app/agent/fallback.py` for why it has to appear late rather than up front.

    `fell_back` covers the case the middleware cannot: the dashboard could not even be
    introspected, so this run is already the database standing in for it and is told to say so.
    """
    web = connector.kind == "web"
    capability = WEB_CAPABILITY if web else SQL_CAPABILITY
    if fell_back:
        capability = fallback.capability()
    today = date.today().isoformat()

    middleware = []
    if web and backup is not None:
        backup_connector, backup_schema = backup
        middleware.append(
            fallback.unlock_database(
                make_query_tool(backup_connector, backup_schema),
                AGENT_SYSTEM.format(today=today, capability=fallback.capability()),
            )
        )

    return create_agent(
        model=get_llm(),
        tools=tools_for(connector, schema),
        system_prompt=AGENT_SYSTEM.format(today=today, capability=capability),
        checkpointer=checkpointer,
        middleware=middleware,
    )

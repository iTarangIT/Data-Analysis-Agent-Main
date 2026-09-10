from datetime import date
from typing import Any

from langchain.agents import create_agent

from app.agent.prompts import AGENT_SYSTEM
from app.agent.tools import make_query_tool
from app.config import get_settings
from app.connectors.base import Connector
from app.llm import get_llm


def recursion_limit() -> int:
    """Bound the tool-calling loop, so a confused model cannot spend a tenant's budget.

    One tool call is a model step plus a tool step, and one final model step writes the
    answer.
    """
    return 2 * get_settings().max_tool_calls + 1


def build_agent(connector: Connector, schema: dict[str, Any], checkpointer=None):
    """The agent decides for itself whether a question needs the database, which replaces the
    explicit router. The web and file tools join this list in phases 3 and 5."""
    return create_agent(
        model=get_llm(),
        tools=[make_query_tool(connector, schema)],
        system_prompt=AGENT_SYSTEM.format(today=date.today().isoformat()),
        checkpointer=checkpointer,
    )

from datetime import date
from typing import Any

from langchain.agents import create_agent

from app.agent.prompts import AGENT_SYSTEM, SQL_CAPABILITY, WEB_CAPABILITY
from app.agent.tools import tools_for
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
    """The agent decides for itself whether a question needs the source, which replaces the
    explicit router. The file tool joins this list in phase 5.

    The capability block is chosen by kind rather than describing every source at once: a
    connection has one kind, so telling a dashboard tenant how to write SQL would only invite
    the model to claim it had.
    """
    capability = WEB_CAPABILITY if connector.kind == "web" else SQL_CAPABILITY
    return create_agent(
        model=get_llm(),
        tools=tools_for(connector, schema),
        system_prompt=AGENT_SYSTEM.format(today=date.today().isoformat(), capability=capability),
        checkpointer=checkpointer,
    )

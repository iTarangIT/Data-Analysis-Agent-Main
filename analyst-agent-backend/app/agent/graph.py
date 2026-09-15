from datetime import date

from langchain.agents import create_agent

from app.agent.prompts import AGENT_SYSTEM, SQL_CAPABILITY
from app.agent.tools import make_query_tool
from app.catalog.types import Catalog
from app.config import get_settings
from app.connectors.base import SqlConnector
from app.llm import get_llm


def recursion_limit() -> int:
    """Bound the tool-calling loop, so a confused model cannot spend a tenant's budget.

    One tool call is a model step plus a tool step, and one final model step writes the
    answer.
    """
    return 2 * get_settings().max_tool_calls + 1


def build_agent(connector: SqlConnector, catalog: Catalog, checkpointer=None):
    return create_agent(
        model=get_llm(),
        tools=[make_query_tool(connector, catalog)],
        system_prompt=AGENT_SYSTEM.format(
            today=date.today().isoformat(), capability=SQL_CAPABILITY
        ),
        checkpointer=checkpointer,
    )

from datetime import date

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langgraph.store.base import BaseStore

from app.agent.context import RunContext
from app.agent.middleware import build_middleware, node_hooks
from app.agent.prompts import AGENT_SYSTEM, capability
from app.agent.tools import make_tools
from app.catalog.types import Catalog
from app.config import get_settings
from app.connectors.base import SqlConnector
from app.forecasting.service import get_forecaster
from app.llm import get_llm


def recursion_limit(middleware: list[AgentMiddleware]) -> int:
    """Bound the tool-calling loop, so a confused model cannot spend a tenant's budget.

    One tool call is a model step plus a tool step, and one final model step writes the answer.
    Middleware hooked on before_model or after_model adds a node to every one of those cycles,
    and one on before_agent or after_agent adds a node to the run, so the bound grows with them.

    The trailing `+ 1` is not slack. LangGraph raises when the superstep count *reaches* the
    limit, so a run that needs exactly N supersteps needs a limit of N + 1. Without it the last
    permitted tool call always failed, and `max_tool_calls` was short by one of what it promised.
    """
    counts = node_hooks(middleware)
    per_cycle = counts["before_model"] + counts["after_model"]
    per_run = counts["before_agent"] + counts["after_agent"]
    supersteps = per_run + get_settings().max_tool_calls * (per_cycle + 2) + per_cycle + 1
    return supersteps + 1


def build_agent(
    connector: SqlConnector,
    catalog: Catalog,
    checkpointer=None,
    store: BaseStore | None = None,
    middleware: list[AgentMiddleware] | None = None,
):
    forecaster = get_forecaster()
    today = date.today()
    return create_agent(
        model=get_llm(),
        tools=make_tools(connector, catalog, store is not None, forecaster=forecaster, today=today),
        system_prompt=AGENT_SYSTEM.format(
            today=today.isoformat(), capability=capability(forecaster is not None)
        ),
        middleware=build_middleware(store is not None) if middleware is None else middleware,
        context_schema=RunContext,
        checkpointer=checkpointer,
        store=store,
    )

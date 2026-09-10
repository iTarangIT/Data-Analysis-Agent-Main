from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.answer import answer_node
from app.agent.nodes.db_exec import make_db_exec_node
from app.agent.nodes.router import router_node
from app.agent.nodes.sql_gen import sql_gen_node
from app.agent.nodes.sql_guard import sql_guard_node
from app.agent.state import AgentState
from app.config import get_settings
from app.connectors.base import Connector

_ROUTE_TO_NODE = {"sql": "sql_gen", "web": "web_tool", "clarify": "answer"}


def _after_router(state: AgentState) -> str:
    return _ROUTE_TO_NODE[state["tool"]]


def _retry_or_answer(state: AgentState) -> str:
    """Both the guard and the executor feed failures back to sql_gen, up to the retry cap."""
    if state.get("guard_error") is None:
        return "db_exec"
    if state.get("retries", 0) <= get_settings().max_sql_retries:
        return "sql_gen"
    return "answer"


def _after_guard(state: AgentState) -> str:
    return _retry_or_answer(state)


def _after_exec(state: AgentState) -> str:
    return "answer" if state.get("guard_error") is None else _retry_or_answer(state)


def _web_tool_unavailable(state: AgentState) -> AgentState:
    return {"error": "web tool not configured"}


def build_graph(
    connector: Connector,
    web_tool_node: Callable[[AgentState], AgentState] | None = None,
    checkpointer=None,
):
    g = StateGraph(AgentState)
    g.add_node("router", router_node)
    g.add_node("sql_gen", sql_gen_node)
    g.add_node("sql_guard", sql_guard_node)
    g.add_node("db_exec", make_db_exec_node(connector))
    g.add_node("answer", answer_node)
    g.add_node("web_tool", web_tool_node or _web_tool_unavailable)

    g.add_edge(START, "router")
    g.add_conditional_edges("router", _after_router, ["sql_gen", "web_tool", "answer"])
    g.add_edge("sql_gen", "sql_guard")
    g.add_conditional_edges("sql_guard", _after_guard, ["db_exec", "sql_gen", "answer"])
    g.add_conditional_edges("db_exec", _after_exec, ["answer", "sql_gen"])
    g.add_edge("web_tool", "answer")
    g.add_edge("answer", END)

    return g.compile(checkpointer=checkpointer)

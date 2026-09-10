from collections.abc import Callable

from langchain_core.tools import BaseTool

from app.agent.state import AgentState


def make_db_exec_node(tool: BaseTool) -> Callable[[AgentState], AgentState]:
    """Runs the guarded SQL through the same tool the model called, so there is one code path
    to the database whether it is reached from the graph or from a direct tool call."""

    def db_exec_node(state: AgentState) -> AgentState:
        result = tool.invoke({"sql": state["sql"]})
        if "error" in result:
            return {"guard_error": result["error"], "retries": state.get("retries", 0) + 1}
        return {
            "columns": result["columns"],
            "rows": result["rows"],
            "truncated": result["truncated"],
            "guard_error": None,
        }

    return db_exec_node

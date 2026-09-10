from collections.abc import Callable

from app.agent.state import AgentState
from app.config import get_settings
from app.connectors.base import Connector


def make_db_exec_node(connector: Connector) -> Callable[[AgentState], AgentState]:
    """Closure so the tenant's connector never has to live in graph state."""

    def db_exec_node(state: AgentState) -> AgentState:
        max_rows = get_settings().max_rows
        try:
            # One row beyond the cap tells us whether the result was truncated.
            cols, rows = connector.run_select(state["sql"], max_rows + 1)
        except Exception as e:
            return {
                "guard_error": f"database error: {e}",
                "retries": state.get("retries", 0) + 1,
            }

        return {
            "columns": cols,
            "rows": [list(r) for r in rows[:max_rows]],
            "truncated": len(rows) > max_rows,
            "guard_error": None,
        }

    return db_exec_node

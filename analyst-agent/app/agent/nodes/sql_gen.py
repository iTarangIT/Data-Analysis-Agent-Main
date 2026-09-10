from collections.abc import Callable
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from app.agent.prompts import SQL_SYSTEM
from app.agent.state import AgentState
from app.llm import get_llm


def make_sql_gen_node(tool: BaseTool) -> Callable[[AgentState], AgentState]:
    """The model writes SQL by calling the query tool, so its output is schema-validated by
    LangChain rather than parsed out of prose. The call is not executed here: the SQL goes
    through the guard node first, and `db_exec` invokes the tool."""

    def sql_gen_node(state: AgentState) -> AgentState:
        msgs = [
            SystemMessage(content=SQL_SYSTEM.format(today=date.today().isoformat())),
            HumanMessage(content=f"Question: {state['question']}"),
        ]
        if state.get("guard_error"):
            msgs.append(
                HumanMessage(
                    content=(
                        f"Your previous SQL was rejected:\n{state.get('sql')}\n"
                        f"Reason: {state['guard_error']}\nWrite a corrected query."
                    )
                )
            )

        llm = get_llm().bind_tools([tool], tool_choice=tool.name)
        calls = llm.invoke(msgs).tool_calls
        if not calls:
            return {
                "guard_error": f"answer by calling the {tool.name} tool with one SELECT",
                "retries": state.get("retries", 0) + 1,
            }
        return {"sql": calls[0]["args"]["sql"].strip(), "guard_error": None}

    return sql_gen_node

import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.prompts import ANSWER_SYSTEM
from app.agent.state import AgentState
from app.llm import get_llm

# Enough rows for the model to characterise the result without overflowing its context.
PREVIEW_ROWS = 50


def answer_node(state: AgentState) -> AgentState:
    preview = {
        "columns": state.get("columns", []),
        "rows": state.get("rows", [])[:PREVIEW_ROWS],
    }
    resp = get_llm(temperature=0.2).invoke(
        [
            SystemMessage(content=ANSWER_SYSTEM),
            HumanMessage(
                content=(
                    f"Question: {state['question']}\n"
                    f"SQL: {state.get('sql')}\n"
                    f"Result: {json.dumps(preview, default=str)}"
                )
            ),
        ]
    )
    return {"answer": resp.content}

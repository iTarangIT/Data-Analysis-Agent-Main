from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.agent.prompts import ROUTER_SYSTEM
from app.agent.state import AgentState
from app.llm import get_llm


class RouteDecision(BaseModel):
    tool: Literal["sql", "web", "clarify"]
    reason: str


def _schema_summary(schema: dict) -> str:
    return "\n".join(
        f"- {t['name']}({', '.join(c['name'] for c in t['columns'])})"
        for t in schema.get("tables", [])
    )


def router_node(state: AgentState) -> AgentState:
    llm = get_llm().with_structured_output(RouteDecision)
    decision: RouteDecision = llm.invoke(
        [
            SystemMessage(content=ROUTER_SYSTEM),
            HumanMessage(
                content=(
                    f"Tables:\n{_schema_summary(state['schema'])}\n\nQuestion: {state['question']}"
                )
            ),
        ]
    )
    return {"tool": decision.tool}

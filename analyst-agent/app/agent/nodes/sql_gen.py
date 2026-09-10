import json
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agent.prompts import SQL_SYSTEM
from app.agent.state import AgentState
from app.llm import get_llm


class SqlDraft(BaseModel):
    """A structured output rather than a bare string, so there are no code fences to strip."""

    sql: str = Field(description="One PostgreSQL SELECT statement, no prose, no code fences.")


def _schema_ddl(schema: dict) -> str:
    parts = []
    for t in schema["tables"]:
        cols = ", ".join(f"{c['name']} {c['type']}" for c in t["columns"])
        sample = json.dumps(t.get("sample", [])[:3])
        parts.append(f"TABLE {t['name']} ({cols})\n  sample rows: {sample}")
    return "\n".join(parts)


def sql_gen_node(state: AgentState) -> AgentState:
    msgs = [
        SystemMessage(content=SQL_SYSTEM.format(today=date.today().isoformat())),
        HumanMessage(
            content=(f"Schema:\n{_schema_ddl(state['schema'])}\n\nQuestion: {state['question']}")
        ),
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

    draft: SqlDraft = get_llm().with_structured_output(SqlDraft).invoke(msgs)
    return {"sql": draft.sql.strip(), "guard_error": None}

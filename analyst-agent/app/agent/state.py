from typing import Any, Literal, TypedDict


class AgentState(TypedDict, total=False):
    """Shared graph state. `total=False` lets each node return only the keys it changed."""

    tenant_id: str
    connection_id: str
    question: str
    schema: dict[str, Any]

    tool: Literal["sql", "web", "clarify"]

    sql: str
    guard_error: str | None
    retries: int
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool

    answer: str
    error: str | None

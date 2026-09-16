"""What wraps the agent loop: the context it is given, and what it keeps afterwards.

Only `before_agent`, `before_model`, `after_model` and `after_agent` become graph nodes, and every
node is a superstep the recursion limit pays for. That is why memory is read once in
`before_agent` and injected through `wrap_model_call`, which adds no node at all, instead of being
read on each model call.
"""

from collections.abc import Callable
from typing import Any, NotRequired

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelRequest,
    ModelResponse,
    SummarizationMiddleware,
)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.runtime import Runtime

from app.agent import memory
from app.agent.context import RunContext
from app.agent.prompts import THREAD_SUMMARY
from app.config import get_settings
from app.llm import get_llm
from app.logging import log

HOOK_NODES = ("before_agent", "before_model", "after_model", "after_agent")


class MemoryState(AgentState):
    memory: NotRequired[str]


def _is_summary(message: Any) -> bool:
    return message.additional_kwargs.get("lc_source") == "summarization"


def _this_turn(messages: list) -> list:
    """The tail of the thread the run that just finished actually produced.

    `state["messages"]` is the whole checkpointed thread, not this run. Harvesting all of it files
    an earlier turn's SQL against this turn's question: ask something conversational that runs no
    query, and the last query of two turns ago is kept as the one that answered it. That pair is
    wrong, and being wrong in the store is worse than being absent - it is offered back as
    precedent on every later run.

    A turn begins at its own question. The summariser writes its summary back in as a
    HumanMessage, so that is the last human turn which is not one of those.
    """
    for i in range(len(messages) - 1, -1, -1):
        message = messages[i]
        if isinstance(message, HumanMessage) and not _is_summary(message):
            return messages[i:]
    return []


def _harvest(messages: list) -> tuple[str, str | None, str, list[tuple[str, str, str]]]:
    """What this run established: the question, the SQL that ran, the answer, and any query the
    model got wrong and then got right.
    """
    turn = _this_turn(messages)
    if not turn:
        return "", None, "", []

    question = turn[0].text
    answer = next(
        (m.text for m in reversed(turn) if isinstance(m, AIMessage) and not m.tool_calls),
        "",
    )

    sql = None
    corrections: list[tuple[str, str, str]] = []
    pending: tuple[str, str] | None = None
    for message in turn:
        if not isinstance(message, ToolMessage) or not message.artifact:
            continue
        artifact = message.artifact
        if artifact.get("error"):
            pending = (artifact.get("sql", ""), artifact["error"])
        else:
            sql = artifact["sql"]
            if pending and pending[0]:
                corrections.append((pending[0], pending[1], sql))
            pending = None

    return question, sql, answer, corrections


class MemoryMiddleware(AgentMiddleware):
    """Puts what earlier conversations established in front of the model, and keeps what this one
    established for the next."""

    state_schema = MemoryState

    def before_agent(self, state: MemoryState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        return {"memory": memory.recall(runtime.store, runtime.context)}

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        block = request.state.get("memory")
        if not block:
            return handler(request)

        prompt = request.system_message.text if request.system_message else ""
        return handler(request.override(system_message=SystemMessage(f"{prompt}\n\n{block}")))

    def after_agent(self, state: MemoryState, runtime: Runtime[RunContext]) -> None:
        question, sql, answer, corrections = _harvest(state["messages"])
        if not question:
            return

        store, ctx = runtime.store, runtime.context
        try:
            memory.remember_thread(store, ctx, question, sql, answer)
            if sql:
                memory.remember_query(store, ctx, question, sql)
            for rejected, reason, corrected in corrections:
                memory.remember_correction(store, ctx, rejected, reason, corrected)
        except Exception:
            # The answer has already been streamed to the customer. Losing the memory of this run
            # is worth far less than turning a delivered answer into a failed one.
            log.warning("memory.write_failed", exc_info=True)


def context_middleware() -> list[AgentMiddleware]:
    """Keep a long thread from costing more every turn.

    Clearing runs first and does the heavy lifting: a cleared tool result is a placeholder rather
    than 50 rows of JSON, it costs no model call, and it edits a copy so nothing reaches the
    checkpoint. Summarising is the fallback for what is left, and does cost a call.
    """
    s = get_settings()
    return [
        ContextEditingMiddleware(
            edits=[ClearToolUsesEdit(trigger=s.clear_tool_results_after_tokens, keep=3)]
        ),
        SummarizationMiddleware(
            model=get_llm(),
            # Without a trigger the middleware is a silent no-op, not a default.
            trigger=("tokens", s.summarize_after_tokens),
            keep=("messages", s.keep_messages),
            summary_prompt=THREAD_SUMMARY,
        ),
    ]


def build_middleware(store_attached: bool) -> list[AgentMiddleware]:
    middleware = context_middleware()
    if store_attached:
        middleware.append(MemoryMiddleware())
    return middleware


def node_hooks(middleware: list[AgentMiddleware]) -> dict[str, int]:
    """How many graph nodes each hook contributes, counted the way `create_agent` counts them.

    `wrap_model_call` and `wrap_tool_call` are absent on purpose: they compose around the model
    and tool nodes rather than adding one, so they cost no superstep.
    """
    counts = dict.fromkeys(HOOK_NODES, 0)
    for m in middleware:
        for hook in HOOK_NODES:
            if getattr(type(m), hook) is not getattr(AgentMiddleware, hook) or getattr(
                type(m), f"a{hook}"
            ) is not getattr(AgentMiddleware, f"a{hook}"):
                counts[hook] += 1
    return counts

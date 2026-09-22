"""Which Gemini tier answers a run, decided once per run by TypeSafe's Jev classifier.

Classifying is a `before_agent` hook, so it costs one node per run and `recursion_limit()`
counts it. Swapping the model is a `wrap_model_call`, which costs nothing, and reaches only the
agent's own calls: the summariser holds its own model and stays on the fast tier.
"""

import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Literal, NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from langchain_typesafe import Noul, NoulCriteria, TypeSafeClassifier
from langgraph.runtime import Runtime

from app.agent.context import RunContext
from app.agent.prompts import ROUTE_DEEP, ROUTE_DEEP_WHEN, ROUTE_FAST_WHEN
from app.config import get_settings
from app.llm import get_llm
from app.logging import log

QUESTION = Noul(
    instructions=ROUTE_DEEP, criteria=NoulCriteria(true=ROUTE_DEEP_WHEN, false=ROUTE_FAST_WHEN)
)


class RouteState(AgentState):
    route: NotRequired[dict[str, Any]]


@lru_cache
def classifier() -> TypeSafeClassifier:
    """One per process, so its connection pool outlives a run and a warm connection answers
    within the timeout."""
    s = get_settings()
    return TypeSafeClassifier(api_key=s.typesafe_api_key, timeout=s.router_timeout_s)


class JevRouter(AgentMiddleware):
    state_schema = RouteState

    def __init__(self, mode: Literal["shadow", "on"]):
        self.mode = mode
        self.deep = get_llm(tier="deep") if mode == "on" else None

    def before_agent(self, state: RouteState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        # Only the question's text. The rest of the thread holds result rows, and Jev is a
        # third party.
        question = state["messages"][-1].text
        t0 = time.perf_counter()
        p_deep: float | None
        try:
            answer = classifier().invoke({"state": question, "questions": {"deep": QUESTION}})
            p_deep = answer.nouls["deep"].noul
        except Exception:
            # The run can always be answered by the model it would have had without routing.
            # Failing it because the classifier is down or slow would be far worse.
            log.warning("router.failed", exc_info=True)
            p_deep = None

        wanted = (
            "deep"
            if p_deep is not None and p_deep >= get_settings().router_deep_threshold
            else "fast"
        )
        return {
            "route": {
                "mode": self.mode,
                "wanted": wanted,
                "used": wanted if self.mode == "on" else "fast",
                "p_deep": p_deep,
                "ms": int((time.perf_counter() - t0) * 1000),
                "reason": "router_error" if p_deep is None else "classified",
            }
        }

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        route = request.state["route"]  # type: ignore[typeddict-item]
        if self.deep and route["used"] == "deep":
            return handler(request.override(model=self.deep))
        return handler(request)

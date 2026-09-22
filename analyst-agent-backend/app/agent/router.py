"""Which tool a run is given, decided once per run by TypeSafe's Jev classifier.

Classifying is a `before_agent` hook, so it costs one node per run and `recursion_limit()`
counts it. Holding the model to the picked tool is a `wrap_model_call`, which costs nothing and
applies to every model call in the run, retries included.
"""

import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Literal, NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from langchain_typesafe import Choice, TypeSafeClassifier
from langgraph.runtime import Runtime

from app.agent.context import RunContext
from app.agent.prompts import ROUTE_CLARIFY, ROUTE_FORECAST, ROUTE_SQL, ROUTE_TOOL
from app.agent.tools import FORECAST_TOOL_NAME, TOOL_NAME
from app.config import get_settings
from app.logging import log

# The labels match `runs.tool`, so a shadow pick can be compared with what the model did.
# `clarify` has no tool: it never restricts, because a data question misjudged as small talk
# would then have no way to reach the data.
DATA_TOOLS = {"sql": TOOL_NAME, "forecast": FORECAST_TOOL_NAME}


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

    def __init__(self, mode: Literal["shadow", "on"], forecasting: bool):
        self.mode = mode
        criteria = {"sql": ROUTE_SQL, "clarify": ROUTE_CLARIFY}
        # Offering a forecast with no forecasting model loaded would let Jev hold the model to
        # a tool it does not have.
        if forecasting:
            criteria["forecast"] = ROUTE_FORECAST
        self.question = Choice(instructions=ROUTE_TOOL, criteria=criteria)

    def before_agent(self, state: RouteState, runtime: Runtime[RunContext]) -> dict[str, Any]:
        # Only the question's text. The rest of the thread holds result rows, and Jev is a
        # third party.
        question = state["messages"][-1].text
        t0 = time.perf_counter()
        picked: str | None
        p: float | None
        try:
            answer = classifier().invoke({"state": question, "questions": {"tool": self.question}})
            choice = answer.choices["tool"]
            picked, p = choice.choice, choice.probabilities[choice.choice]
        except Exception:
            # The run can always go ahead with every tool, as it would without routing. Failing
            # it because the classifier is down or slow would be far worse.
            log.warning("router.failed", exc_info=True)
            picked = p = None

        if p is None:
            reason = "router_error"
        elif p < get_settings().router_threshold:
            reason = "unsure"
        else:
            reason = "classified"
        return {
            "route": {
                "mode": self.mode,
                "picked": picked,
                "p": p,
                "ms": int((time.perf_counter() - t0) * 1000),
                "reason": reason,
                "restricted": self.mode == "on" and reason == "classified" and picked in DATA_TOOLS,
            }
        }

    def wrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
    ) -> ModelResponse:
        route = request.state["route"]  # type: ignore[typeddict-item]
        if not route["restricted"]:
            return handler(request)
        # Only the other data tool is taken away. `remember` is not an answer to the question,
        # so it stays whichever tool was picked.
        others = {name for label, name in DATA_TOOLS.items() if label != route["picked"]}
        tools = [t for t in request.tools if isinstance(t, dict) or t.name not in others]
        return handler(request.override(tools=tools))

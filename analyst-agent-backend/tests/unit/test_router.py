"""The Jev router: which tool a run is given, and what the run keeps about that choice.

Jev is the real `TypeSafeClassifier` over a mock transport, so the package's own request and
response handling runs and nothing reaches the network.
"""

import json
from unittest.mock import patch

import httpx2
import pytest
from langchain_core.messages import AIMessage
from langchain_typesafe import TypeSafeClassifier
from langgraph.store.memory import InMemoryStore
from pydantic import Field, SecretStr, ValidationError

from app.agent.graph import build_agent, recursion_limit
from app.agent.middleware import build_middleware
from app.agent.router import classifier
from app.config import Settings, get_settings
from app.forecasting.service import ForecastService
from tests.unit.test_middleware import (
    CATALOG,
    CONTEXT,
    FakeConnector,
    FakeToolModel,
    FlatEngine,
    _tool_call,
)

QUESTION = "what will revenue be next quarter"
EVERY_TOOL = ["forecast_series", "query_database"]


class OfferedTools(FakeToolModel):
    """Keeps the names of the tools each model call was given."""

    offered: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.offered.append(sorted(t.name for t in tools))
        return self


def picking(label, p, seen=None):
    def handle(request):
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        ((question_id, question),) = body["questions"].items()
        labels = list(question["criteria"])
        rest = (1 - p) / (len(labels) - 1)
        return httpx2.Response(
            200,
            json={
                "model": "jev-1",
                "answers": {
                    question_id: {
                        "type": "choice",
                        "choice": label,
                        "probabilities": {x: p if x == label else rest for x in labels},
                        "confidence": p,
                    }
                },
                "usage": {"input_tokens": 60, "output_tokens": 1},
            },
        )

    return handle


def failing(request):
    return httpx2.Response(500, json={"error": {"message": "internal error"}})


def timing_out(request):
    raise httpx2.ReadTimeout("no answer in time", request=request)


@pytest.fixture
def routing(monkeypatch):
    def set_mode(mode):
        monkeypatch.setattr(get_settings(), "router_mode", mode, raising=False)
        monkeypatch.setattr(get_settings(), "router_threshold", 0.7, raising=False)

    return set_mode


def ask(handler, *, forecasting=True, store=None, responses=None):
    """One run through the real agent. Returns the route it recorded and the tools each model
    call was offered."""
    model = OfferedTools(responses=responses or [AIMessage(content="Done.")])
    forecaster = ForecastService(FlatEngine()) if forecasting else None
    jev = TypeSafeClassifier(
        api_key="test", client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    with (
        patch("app.agent.graph.get_llm", return_value=model),
        patch("app.agent.middleware.get_llm", return_value=model),
        patch("app.agent.graph.get_forecaster", return_value=forecaster),
        patch("app.agent.middleware.get_forecaster", return_value=forecaster),
        patch("app.agent.router.classifier", return_value=jev),
    ):
        middleware = build_middleware(store is not None)
        agent = build_agent(FakeConnector(), CATALOG, store=store, middleware=middleware)
        updates = [
            (node, update)
            for chunk in agent.stream(
                {"messages": [("user", QUESTION)]},
                config={"recursion_limit": recursion_limit(middleware)},
                context=CONTEXT,
                stream_mode="updates",
            )
            for node, update in chunk.items()
        ]

    # `execute_run` reads the route from exactly this update, so asserting on it here covers
    # what reaches `runs.trace`.
    route = next((u["route"] for n, u in updates if n == "JevRouter.before_agent"), None)
    return route, model.offered


class TestOff:
    def test_off_never_asks_jev_and_offers_every_tool(self, routing):
        routing("off")
        seen = []

        route, offered = ask(picking("sql", 0.9, seen))

        assert seen == []
        assert route is None
        assert offered == [EVERY_TOOL]


class TestShadow:
    def test_the_pick_is_recorded_and_every_tool_is_still_offered(self, routing):
        routing("shadow")

        route, offered = ask(picking("forecast", 0.9))

        assert offered == [EVERY_TOOL]
        assert isinstance(route.pop("ms"), int)
        assert route == {
            "mode": "shadow",
            "picked": "forecast",
            "p": 0.9,
            "reason": "classified",
            "restricted": False,
        }

    def test_only_the_question_is_sent_to_typesafe(self, routing):
        """Jev is a third party. Thread history holds result rows, which must never leave."""
        routing("shadow")
        seen = []

        ask(picking("sql", 0.9, seen))

        assert [body["state"] for body in seen] == [QUESTION]


class TestOn:
    def test_a_forecast_question_is_offered_only_the_forecast_tool(self, routing):
        routing("on")

        route, offered = ask(picking("forecast", 0.9))

        assert offered == [["forecast_series"]]
        assert route["restricted"] is True

    def test_a_data_question_is_held_to_the_query_tool_on_every_call(self, routing):
        routing("on")

        _, offered = ask(
            picking("sql", 0.9),
            responses=[_tool_call("select vehicleno from vehicles"), AIMessage(content="One.")],
        )

        assert offered == [["query_database"], ["query_database"]]

    def test_remember_is_never_taken_away(self, routing):
        routing("on")

        _, offered = ask(picking("sql", 0.9), store=InMemoryStore())

        assert offered == [["query_database", "remember"]]

    def test_a_clarify_pick_leaves_every_tool(self, routing):
        """A data question misjudged as small talk must still be able to reach the data."""
        routing("on")

        route, offered = ask(picking("clarify", 0.95))

        assert offered == [EVERY_TOOL]
        assert route["picked"] == "clarify" and route["restricted"] is False

    @pytest.mark.parametrize(
        ("p", "reason", "want"),
        [(0.69, "unsure", EVERY_TOOL), (0.7, "classified", ["forecast_series"])],
        ids=["below the threshold", "at the threshold"],
    )
    def test_jev_is_followed_only_when_sure_enough(self, routing, p, reason, want):
        routing("on")

        route, offered = ask(picking("forecast", p))

        assert offered == [want]
        assert route["reason"] == reason


class TestWithoutForecasting:
    def test_jev_is_not_offered_a_forecast_when_no_model_is_loaded(self, routing):
        """Picking it would hold the model to a tool it does not have, leaving it none."""
        routing("on")
        seen = []

        ask(picking("sql", 0.9, seen), forecasting=False)

        assert sorted(seen[0]["questions"]["tool"]["criteria"]) == ["clarify", "sql"]


class TestAFailingRouterDoesNotFailTheRun:
    """Jev is an early-access service in front of every question. When it fails the run carries
    on as it would without routing, and says why."""

    @pytest.mark.parametrize("handler", [failing, timing_out], ids=["error", "timeout"])
    def test_every_tool_is_offered(self, routing, handler):
        routing("on")

        route, offered = ask(handler)

        assert offered == [EVERY_TOOL]
        assert route["reason"] == "router_error"
        assert route["picked"] is None and route["p"] is None
        assert route["restricted"] is False


class TestConfiguration:
    @pytest.mark.parametrize("key", [None, ""], ids=["unset", "empty, as .env.example has it"])
    def test_routing_without_a_typesafe_key_fails_at_boot(self, key):
        """Otherwise every run of a shadow fortnight would quietly record `router_error`."""
        with pytest.raises(ValidationError, match="TYPESAFE_API_KEY"):
            Settings(_env_file=None, router_mode="shadow", typesafe_api_key=key)

        assert Settings(_env_file=None, router_mode="shadow", typesafe_api_key="k").router_mode

    def test_jev_is_held_to_the_router_timeout(self, monkeypatch):
        """The package waits 30 seconds by default, in front of every run's first model call."""
        monkeypatch.setattr(get_settings(), "typesafe_api_key", SecretStr("k"), raising=False)
        monkeypatch.setattr(get_settings(), "router_timeout_s", 1.5, raising=False)
        classifier.cache_clear()
        try:
            assert classifier().client.timeout == httpx2.Timeout(1.5)
        finally:
            classifier.cache_clear()

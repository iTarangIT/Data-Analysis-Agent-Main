"""The Jev router: which Gemini tier answers a run, and what the run keeps about that choice.

Jev is the real `TypeSafeClassifier` over a mock transport, so the package's own request and
response handling runs and nothing reaches the network.
"""

import json
from unittest.mock import patch

import httpx2
import pytest
from langchain_core.messages import AIMessage
from langchain_typesafe import TypeSafeClassifier
from pydantic import SecretStr, ValidationError

from app.agent.graph import build_agent, recursion_limit
from app.agent.middleware import build_middleware
from app.agent.router import classifier
from app.config import Settings, get_settings
from app.llm import get_llm
from tests.unit.test_middleware import CATALOG, CONTEXT, FakeConnector, FakeToolModel

QUESTION = "how many vehicles went offline last week"


def answering(p_deep, seen=None):
    def handle(request):
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        (question_id,) = body["questions"]
        return httpx2.Response(
            200,
            json={
                "model": "jev-1",
                "answers": {question_id: {"type": "noul", "noul": p_deep}},
                "usage": {"input_tokens": 40, "output_tokens": 1},
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
        monkeypatch.setattr(get_settings(), "router_deep_threshold", 0.7, raising=False)

    return set_mode


def ask(handler):
    """One run through the real agent, returning the route it recorded and who answered."""
    fast = FakeToolModel(responses=[AIMessage(content="Answered by the fast model.")])
    deep = FakeToolModel(responses=[AIMessage(content="Answered by the deep model.")])

    def tiers(tier="fast"):
        return {"fast": fast, "deep": deep}[tier]

    jev = TypeSafeClassifier(
        api_key="test", client=httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    with (
        patch("app.agent.graph.get_llm", side_effect=tiers),
        patch("app.agent.middleware.get_llm", side_effect=tiers),
        patch("app.agent.router.get_llm", side_effect=tiers),
        patch("app.agent.router.classifier", return_value=jev),
    ):
        middleware = build_middleware(False)
        agent = build_agent(FakeConnector(), CATALOG, middleware=middleware)
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
    answer = next(m.text for n, u in updates if n == "model" for m in u["messages"])
    return route, answer


class TestOff:
    def test_off_never_asks_jev_and_records_no_route(self, routing):
        routing("off")
        seen = []

        route, answer = ask(answering(0.9, seen))

        assert seen == []
        assert route is None
        assert answer == "Answered by the fast model."


class TestShadow:
    def test_a_hard_question_is_recorded_as_deep_but_answered_by_fast(self, routing):
        routing("shadow")

        route, answer = ask(answering(0.9))

        assert answer == "Answered by the fast model."
        assert route["mode"] == "shadow"
        assert route["wanted"] == "deep"
        assert route["used"] == "fast"
        assert route["p_deep"] == 0.9
        assert route["reason"] == "classified"
        assert isinstance(route["ms"], int) and route["ms"] >= 0

    def test_only_the_question_is_sent_to_typesafe(self, routing):
        """Jev is a third party. Thread history holds result rows, which must never leave."""
        routing("shadow")
        seen = []

        ask(answering(0.1, seen))

        assert [body["state"] for body in seen] == [QUESTION]


class TestOn:
    def test_a_hard_question_is_answered_by_the_deep_model(self, routing):
        routing("on")

        route, answer = ask(answering(0.9))

        assert answer == "Answered by the deep model."
        assert route["wanted"] == "deep" and route["used"] == "deep"

    def test_an_easy_question_stays_on_the_fast_model(self, routing):
        routing("on")

        route, answer = ask(answering(0.2))

        assert answer == "Answered by the fast model."
        assert route["wanted"] == "fast" and route["used"] == "fast"

    def test_a_probability_exactly_at_the_threshold_goes_deep(self, routing):
        routing("on")

        route, answer = ask(answering(0.7))

        assert answer == "Answered by the deep model."
        assert route["used"] == "deep"


class TestAFailingRouterDoesNotFailTheRun:
    """Jev is an early-access service in front of every question. When it fails the run carries
    on with the model it would have used anyway, and says why."""

    @pytest.mark.parametrize("handler", [failing, timing_out], ids=["error", "timeout"])
    def test_the_fast_model_answers(self, routing, handler):
        routing("on")

        route, answer = ask(handler)

        assert answer == "Answered by the fast model."
        assert route["reason"] == "router_error"
        assert route["p_deep"] is None
        assert route["wanted"] == "fast" and route["used"] == "fast"


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

    def test_the_deep_tier_is_its_own_gemini_model(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "gemini_model", "gemini-fast-x", raising=False)
        monkeypatch.setattr(get_settings(), "gemini_model_deep", "gemini-deep-x", raising=False)

        assert get_llm().model == "gemini-fast-x"
        assert get_llm(tier="deep").model == "gemini-deep-x"

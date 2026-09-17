"""Tracing is switched on in every process that runs the agent, and a trace is found by its run."""

import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tracers.run_collector import RunCollectorCallbackHandler
from pydantic import SecretStr

from app.agent.graph import build_agent, recursion_limit
from app.agent.middleware import build_middleware
from app.db.models import Run
from app.llm import configure_tracing
from app.services.runs import agent_config
from tests.unit.test_agent import CATALOG, CONTEXT, FakeConnector, FakeToolModel

TRACING_VARS = ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT")

RUN = Run(id=str(uuid.uuid4()), tenant_id="t_test", thread_id="th1", connection_id="c1")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # monkeypatch puts every variable back on teardown, so a key a test exports can never leak
    # into the rest of the suite and start posting its runs to LangSmith.
    for name in TRACING_VARS:
        monkeypatch.delenv(name, raising=False)


def _settings(**overrides):
    values = {
        "langsmith_tracing": True,
        "langsmith_api_key": SecretStr("lsv2_test"),
        "langsmith_project": "analyst-agent-test",
        "langsmith_endpoint": None,
    }
    return SimpleNamespace(**(values | overrides))


class TestConfigureTracing:
    def test_it_exports_what_the_sdk_reads(self):
        endpoint = "https://eu.api.smith.langchain.com"
        with patch("app.llm.get_settings", return_value=_settings(langsmith_endpoint=endpoint)):
            configure_tracing()

        assert os.environ["LANGSMITH_TRACING"] == "true"
        assert os.environ["LANGSMITH_API_KEY"] == "lsv2_test"
        assert os.environ["LANGSMITH_PROJECT"] == "analyst-agent-test"
        assert os.environ["LANGSMITH_ENDPOINT"] == endpoint

    def test_no_endpoint_leaves_the_sdk_on_its_default_region(self):
        with patch("app.llm.get_settings", return_value=_settings()):
            configure_tracing()

        assert "LANGSMITH_ENDPOINT" not in os.environ

    @pytest.mark.parametrize(
        "overrides", [{"langsmith_tracing": False}, {"langsmith_api_key": None}]
    )
    def test_it_exports_nothing_unless_switched_on_with_a_key(self, overrides):
        with patch("app.llm.get_settings", return_value=_settings(**overrides)):
            configure_tracing()

        assert not any(name in os.environ for name in TRACING_VARS)


class TestWorkerStartup:
    async def test_the_worker_switches_tracing_on_itself(self):
        # The worker never runs the API's lifespan, so without its own call every queued run
        # went untraced while the in-process ones were traced.
        from app.workers.runs import _startup

        with patch("app.workers.runs.configure_tracing") as configure:
            await _startup({})

        configure.assert_called_once_with()


class TestTraceIdentity:
    def test_the_config_names_the_run_and_its_thread(self):
        config = agent_config(RUN, [], limit=9)

        assert config["run_id"] == uuid.UUID(RUN.id)
        # The tenant prefix, so two tenants' conversations never merge in the Threads view.
        assert config["metadata"]["thread_id"] == config["configurable"]["thread_id"]
        assert config["metadata"]["thread_id"] == "t_test:th1"
        assert config["metadata"]["tenant_id"] == "t_test"
        assert config["recursion_limit"] == 9

    def test_the_whole_run_is_one_trace_under_the_run_rows_id(self):
        """What the config promises, checked against a tracer rather than read off the dict.

        The collector goes in through `callbacks`, which is inherited the way LangSmith's own
        tracer is. `collect_runs()` attaches its collector non-inheritably, LangGraph's nodes
        never report to it, and the model call then shows up as a second, parentless trace.
        """
        collector = RunCollectorCallbackHandler()
        model = FakeToolModel(responses=[AIMessage(content="Two vehicles.")])
        with (
            patch("app.agent.graph.get_llm", return_value=model),
            patch("app.agent.middleware.get_llm", return_value=model),
        ):
            middleware = build_middleware(False)
            agent = build_agent(FakeConnector(), CATALOG, middleware=middleware)
            config = agent_config(RUN, [collector], limit=recursion_limit(middleware))
            list(agent.stream({"messages": [("user", "how many")]}, config, context=CONTEXT))

        [root] = collector.traced_runs
        assert root.id == uuid.UUID(RUN.id)
        assert root.name == "analyst_run"
        assert root.metadata["thread_id"] == "t_test:th1"
        assert root.metadata["connection_id"] == "c1"

        def descendants(run):
            for child in run.child_runs:
                yield child
                yield from descendants(child)

        model_calls = [r for r in descendants(root) if r.run_type == "llm"]
        assert model_calls
        assert all(r.trace_id == root.id for r in model_calls)

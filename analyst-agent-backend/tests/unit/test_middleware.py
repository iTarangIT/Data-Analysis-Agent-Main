"""The middleware around the agent loop: what it costs in graph nodes, what it tells the model it
already knows, and what it keeps afterwards."""

from typing import ClassVar
from unittest.mock import patch

import numpy as np
import pytest
from langchain.agents.middleware import AgentMiddleware, SummarizationMiddleware
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from app.agent import memory
from app.agent.context import RunContext
from app.agent.graph import build_agent, recursion_limit
from app.agent.middleware import MemoryMiddleware, build_middleware, node_hooks
from app.catalog.types import Catalog, CatalogTable, Column, TableDef
from app.config import get_settings
from app.forecasting.engine import EngineForecast
from app.forecasting.service import ForecastService
from app.services.runs import EventTranslator, RunOutcome

CONTEXT = RunContext(tenant_id="t_one", connection_id="c1", run_id="r1", thread_id="th1")
CATALOG = Catalog(
    tables=[
        CatalogTable(
            definition=TableDef(name="vehicles", columns=[Column(name="vehicleno", type="text")])
        )
    ]
)


class FakeToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class RecordingModel(FakeToolModel):
    """Keeps what it was asked, so a test can assert on the prompt the agent actually built."""

    seen: ClassVar[list] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        type(self).seen.append(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class FakeConnector:
    kind = "postgres"
    dialect = "postgres"

    def __init__(self):
        self.executed: list[str] = []

    def run_select(self, sql, max_rows):
        self.executed.append(sql)
        return ["vehicleno"], [("KA01",)]


def _tool_call(sql, call_id="c1"):
    return AIMessage(
        content="", tool_calls=[{"name": "query_database", "args": {"sql": sql}, "id": call_id}]
    )


def run(model, store=None, context=CONTEXT, question="how many vehicles"):
    connector = FakeConnector()
    with (
        patch("app.agent.graph.get_llm", return_value=model),
        patch("app.agent.middleware.get_llm", return_value=model),
    ):
        # Built inside the patch: SummarizationMiddleware resolves its model at construction,
        # so building it outside hands the summariser a real Gemini client.
        middleware = build_middleware(store is not None)
        agent = build_agent(connector, CATALOG, store=store, middleware=middleware)
        list(
            agent.stream(
                {"messages": [("user", question)]},
                config={"recursion_limit": recursion_limit(middleware)},
                context=context,
                stream_mode="updates",
            )
        )
    return connector


class TestSummarisationIsActuallyArmed:
    """`trigger` defaults to None, and a summariser built without one can never run. It fails
    silently: the agent still works and context simply keeps growing."""

    def test_the_summariser_is_given_a_trigger(self):
        summariser = next(
            m for m in build_middleware(False) if isinstance(m, SummarizationMiddleware)
        )
        assert summariser._trigger_clauses, "summarisation is configured but can never fire"


class TestNodeCost:
    """Only these four hooks become graph nodes. A wrap hook composes around the model and tool
    nodes instead, which is why reading memory is free and the recursion limit ignores it."""

    def test_reading_memory_adds_no_node_to_the_cycle(self):
        assert node_hooks([MemoryMiddleware()])["before_model"] == 0

    def test_reading_and_writing_memory_cost_one_node_each_per_run(self):
        counts = node_hooks([MemoryMiddleware()])
        assert counts["before_agent"] == 1 and counts["after_agent"] == 1

    def test_summarisation_costs_a_node_on_every_cycle(self):
        assert node_hooks(build_middleware(False))["before_model"] == 1

    def test_no_middleware_costs_nothing(self):
        assert set(node_hooks([]).values()) == {0}


class TestTheSseContractIsUnaffected:
    """`EventTranslator` dispatches on an exact node name, and middleware nodes are named
    `<middleware>.<hook>`. Summarisation's update carries the whole preserved message tail, so a
    prefix match here would replay a thread's history to the customer as `token` events."""

    @pytest.mark.parametrize(
        "node",
        [
            "SummarizationMiddleware.before_model",
            "MemoryMiddleware.before_agent",
            "MemoryMiddleware.after_agent",
        ],
    )
    def test_a_middleware_node_emits_nothing(self, node):
        translator = EventTranslator(RunOutcome())

        assert list(translator.for_message(node, AIMessage(content="internal"))) == []

    def test_the_middleware_nodes_are_named_the_way_the_filter_assumes(self):
        with patch("app.agent.graph.get_llm"), patch("app.agent.middleware.get_llm"):
            agent = build_agent(FakeConnector(), CATALOG, store=InMemoryStore())

        nodes = set(agent.get_graph().nodes)
        assert "SummarizationMiddleware.before_model" in nodes
        assert "MemoryMiddleware.before_agent" in nodes
        assert {"model", "tools"} <= nodes


class TestMemoryReachesTheModel:
    def test_a_remembered_definition_is_put_in_front_of_the_model(self):
        store = InMemoryStore()
        memory.remember_definition(store, CONTEXT, "net revenue", "sales minus refunds")
        RecordingModel.seen = []

        run(RecordingModel(responses=[AIMessage(content="Done.")]), store=store)

        assert "net revenue: sales minus refunds" in RecordingModel.seen[0][0].text

    def test_a_connection_with_no_history_adds_nothing_to_the_prompt(self):
        RecordingModel.seen = []

        run(RecordingModel(responses=[AIMessage(content="Done.")]), store=InMemoryStore())

        assert "What you already know" not in RecordingModel.seen[0][0].text

    def test_without_a_store_no_memory_middleware_is_attached(self):
        assert not any(isinstance(m, MemoryMiddleware) for m in build_middleware(False))


def run_thread(model, store, questions, context=CONTEXT):
    """Drive several turns down one checkpointed thread, the way a real conversation arrives.

    `run` builds a fresh graph per call, so nothing it drives ever carries a previous turn's
    messages into `after_agent` - which is exactly the shape that hid what this covers.
    """
    connector = FakeConnector()
    with (
        patch("app.agent.graph.get_llm", return_value=model),
        patch("app.agent.middleware.get_llm", return_value=model),
    ):
        middleware = build_middleware(store is not None)
        agent = build_agent(
            connector, CATALOG, checkpointer=InMemorySaver(), store=store, middleware=middleware
        )
        for question in questions:
            list(
                agent.stream(
                    {"messages": [("user", question)]},
                    config={
                        "recursion_limit": recursion_limit(middleware),
                        "configurable": {"thread_id": context.thread_id},
                    },
                    context=context,
                    stream_mode="updates",
                )
            )
    return connector


class TestATurnKeepsOnlyWhatItDid:
    """A thread hands its whole history to the next run's state, so what a run keeps has to be
    what that run did - not the last thing the thread happened to do."""

    def _questions(self, store):
        return sorted(
            item.value["question"] for item in store.search(("t_one", "c1", memory.QUERIES))
        )

    def test_a_conversational_turn_does_not_inherit_the_previous_query(self):
        store = InMemoryStore()
        model = FakeToolModel(
            responses=[
                _tool_call("select vehicleno from vehicles"),
                AIMessage(content="One vehicle."),
                AIMessage(content="You asked how many vehicles there are."),
            ]
        )

        run_thread(model, store, ["how many vehicles", "what did I just ask?"])

        kept = store.get(("t_one", memory.THREADS), "th1").value
        assert kept["question"] == "what did I just ask?"
        assert kept["sql"] is None
        assert kept["answer"] == "You asked how many vehicles there are."
        assert self._questions(store) == ["how many vehicles"]

    def test_a_second_query_is_kept_against_its_own_question(self):
        store = InMemoryStore()
        model = FakeToolModel(
            responses=[
                _tool_call("select vehicleno from vehicles"),
                AIMessage(content="One vehicle."),
                _tool_call("select count(*) from vehicles", "c2"),
                AIMessage(content="One."),
            ]
        )

        run_thread(model, store, ["how many vehicles", "and how many are online?"])

        assert self._questions(store) == ["and how many are online?", "how many vehicles"]
        later = next(
            item.value
            for item in store.search(("t_one", "c1", memory.QUERIES))
            if item.value["question"] == "and how many are online?"
        )
        assert "COUNT(*)" in later["sql"].upper()

    def test_an_earlier_correction_is_not_refiled_by_a_later_turn(self):
        store = InMemoryStore()
        model = FakeToolModel(
            responses=[
                _tool_call("delete from vehicles"),
                _tool_call("select vehicleno from vehicles", "c2"),
                AIMessage(content="One vehicle."),
                AIMessage(content="Nothing to query there."),
            ]
        )

        run_thread(model, store, ["how many vehicles", "thanks"])

        # The correction the first turn earned is still there, and the second turn - which ran
        # nothing - neither repeated it nor attached the first turn's SQL to "thanks".
        assert memory.recall_correction(store, CONTEXT, "delete from vehicles") is not None
        assert store.get(("t_one", memory.THREADS), "th1").value["sql"] is None
        assert self._questions(store) == ["how many vehicles"]


class TestWhatARunKeeps:
    def _answering_model(self):
        return FakeToolModel(
            responses=[
                _tool_call("select vehicleno from vehicles"),
                AIMessage(content="One vehicle."),
            ]
        )

    def test_the_thread_keeps_the_question_the_sql_and_the_answer(self):
        store = InMemoryStore()
        run(self._answering_model(), store=store)

        kept = store.get(("t_one", memory.THREADS), "th1").value
        assert kept["question"] == "how many vehicles"
        assert kept["answer"] == "One vehicle."
        assert kept["sql"].upper().startswith("SELECT")

    def test_the_query_is_offered_back_on_a_later_run(self):
        store = InMemoryStore()
        run(self._answering_model(), store=store)

        assert "how many vehicles" in memory.recall(store, CONTEXT)

    def test_a_refusal_followed_by_a_success_is_kept_as_a_correction(self):
        store = InMemoryStore()
        model = FakeToolModel(
            responses=[
                _tool_call("delete from vehicles"),
                _tool_call("select vehicleno from vehicles", "c2"),
                AIMessage(content="One vehicle."),
            ]
        )

        run(model, store=store)

        fix = memory.recall_correction(store, CONTEXT, "delete from vehicles")
        assert fix["corrected"].upper().startswith("SELECT")

    def test_a_question_answered_without_sql_keeps_no_query(self):
        store = InMemoryStore()

        run(
            FakeToolModel(responses=[AIMessage(content="I only answer data questions.")]),
            store=store,
        )

        assert store.get(("t_one", memory.THREADS), "th1").value["sql"] is None
        assert store.search(("t_one", "c1", memory.QUERIES)) == []


class TestAFailingStoreDoesNotFailTheRun:
    """The answer has already reached the customer by the time memory is written. Losing the
    memory of a run is worth far less than turning a delivered answer into a failure."""

    def test_the_run_finishes_when_the_store_refuses_a_write(self):
        class Broken(InMemoryStore):
            def put(self, *args, **kwargs):
                raise RuntimeError("store is down")

        connector = run(
            FakeToolModel(
                responses=[
                    _tool_call("select vehicleno from vehicles"),
                    AIMessage(content="One vehicle."),
                ]
            ),
            store=Broken(),
        )

        assert connector.executed, "the run never reached the database"


class TestMiddlewareOrder:
    def test_clearing_runs_before_summarising(self):
        """Clearing a tool result costs nothing and summarising costs a model call. Reversed,
        the agent would pay to summarise rows that were about to be thrown away."""
        names = [type(m).__name__ for m in build_middleware(False)]

        assert names.index("ContextEditingMiddleware") < names.index("SummarizationMiddleware")

    def test_every_middleware_has_a_distinct_name(self):
        """create_agent refuses duplicates, and it refuses them with a bare AssertionError."""
        middleware: list[AgentMiddleware] = build_middleware(True)

        assert len({m.name for m in middleware}) == len(middleware)


class TestSummarisationActuallyFiring:
    """The tests above feed the translator a middleware node name by hand. This one makes
    summarisation really run, because what it emits is the thing that would leak: its update
    carries the summary plus the whole preserved tail, including an AIMessage and a ToolMessage
    that look exactly like the ones the model and tool nodes produce."""

    @pytest.fixture
    def always_summarise(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "summarize_after_tokens", 50, raising=False)
        monkeypatch.setattr(get_settings(), "keep_messages", 2, raising=False)

    def _drive(self):
        agent_model = FakeToolModel(
            responses=[
                _tool_call("select vehicleno from vehicles"),
                AIMessage(content="Two vehicles."),
            ]
        )
        # The summariser gets its own model, as it would in production where it may be a cheaper
        # one. Sharing the agent's fake meant the summary call ate the agent's scripted replies.
        summariser = FakeToolModel(
            responses=[AIMessage(content="A summary of the thread.") for _ in range(10)]
        )
        connector = FakeConnector()
        outcome = RunOutcome()
        translator = EventTranslator(outcome)
        events, nodes = [], []
        with (
            patch("app.agent.graph.get_llm", return_value=agent_model),
            patch("app.agent.middleware.get_llm", return_value=summariser),
        ):
            middleware = build_middleware(False)
            agent = build_agent(connector, CATALOG, middleware=middleware)
            for chunk in agent.stream(
                {"messages": [("user", "how many vehicles")]},
                config={"recursion_limit": recursion_limit(middleware)},
                context=CONTEXT,
                stream_mode="updates",
            ):
                for node, update in chunk.items():
                    nodes.append(node)
                    for message in (update or {}).get("messages", []):
                        events.extend(translator.for_message(node, message))
        return events, nodes

    def test_the_summariser_really_ran(self, always_summarise):
        """Guards the test below: if summarisation stops firing it proves nothing."""
        _, nodes = self._drive()

        assert "SummarizationMiddleware.before_model" in nodes

    def test_the_stage_sequence_is_still_the_frozen_one(self, always_summarise):
        events, _ = self._drive()
        stages = [e["data"]["stage"] for e in events if e["type"] == "status"]

        assert stages == ["router", "sql_gen", "sql_guard", "db_exec", "answer"]

    def test_the_preserved_history_is_not_replayed_to_the_customer(self, always_summarise):
        """The summariser re-emits earlier messages. Every one of them reaching the client as a
        token event is what an inexact node filter would cause."""
        events, _ = self._drive()

        assert [e["type"] for e in events].count("token") == 1
        assert "A summary of the thread." not in [
            e["data"].get("text") for e in events if e["type"] == "token"
        ]


class FlatEngine:
    name = "flat"
    max_context = 1024
    max_horizon = 256

    def predict(self, values, horizon):
        mean = np.full(horizon, values[-1])
        return EngineForecast(mean=mean, lower=mean - 1, upper=mean + 1)


class TestAForecastRefusalIsNotACorrection:
    def test_sound_sql_the_forecaster_could_not_use_is_not_filed_as_refused(self):
        # FakeConnector returns only `vehicleno`, so the forecaster refuses for a missing
        # column. The query that follows is the same SQL, and was never wrong.
        store = InMemoryStore()
        forecast = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "forecast_series",
                    "args": {
                        "sql": "select vehicleno from vehicles", "time_column": "day",
                        "value_column": "n", "grain": "day", "horizon": 3, "kind": "total",
                    },
                    "id": "f1",
                }
            ],
        )  # fmt: skip
        model = FakeToolModel(
            responses=[
                forecast,
                _tool_call("select vehicleno from vehicles", "c2"),
                AIMessage(content="One."),
            ]
        )

        with patch("app.agent.graph.get_forecaster", return_value=ForecastService(FlatEngine())):
            run(model, store=store)

        assert store.search(("t_one", "c1", memory.CORRECTIONS)) == []

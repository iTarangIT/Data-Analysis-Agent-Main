"""The agent end to end with a scripted model, and the mapping onto the SSE contract."""

from unittest.mock import patch

import numpy as np
import pytest
from langchain_core.language_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.errors import GraphRecursionError
from langgraph.store.memory import InMemoryStore

from app.agent.context import RunContext
from app.agent.graph import build_agent, recursion_limit
from app.agent.middleware import build_middleware
from app.agent.prompts import FORECAST_CAPABILITY, FORECAST_OFF
from app.catalog.types import Catalog, CatalogTable, Column, TableDef
from app.config import get_settings
from app.forecasting.engine import EngineForecast
from app.forecasting.service import ForecastService
from app.services.runs import EventTranslator, RunOutcome

CONTEXT = RunContext(tenant_id="t_test", connection_id="c1", run_id="r1", thread_id="th1")

CATALOG = Catalog(
    tables=[
        CatalogTable(
            definition=TableDef(
                name="vehicles",
                columns=[Column(name="vehicleno", type="text"), Column(name="owner", type="text")],
            )
        )
    ]
)


class FakeToolModel(FakeMessagesListChatModel):
    """create_agent binds tools to the model, which the stock fake does not support."""

    def bind_tools(self, tools, **kwargs):
        return self


class FakeConnector:
    kind = "postgres"
    dialect = "postgres"

    def __init__(self, rows=(("KA01",), ("KA02",))):
        self.rows = [tuple(r) for r in rows]
        self.columns = ["vehicleno"]
        self.executed: list[str] = []

    def run_select(self, sql, max_rows):
        self.executed.append(sql)
        return self.columns, self.rows[:max_rows]


def _tool_call(sql, **explained):
    return AIMessage(
        content="",
        tool_calls=[{"name": "query_database", "args": {"sql": sql, **explained}, "id": "c1"}],
    )


def _run(model, connector, store=None, question="how many vehicles", limit=None):
    outcome = RunOutcome()
    translator = EventTranslator(outcome)
    events = []
    with (
        patch("app.agent.graph.get_llm", return_value=model),
        patch("app.agent.middleware.get_llm", return_value=model),
    ):
        # Built inside the patch: SummarizationMiddleware resolves its model at construction.
        middleware = build_middleware(store is not None)
        agent = build_agent(connector, CATALOG, store=store, middleware=middleware)
        for chunk in agent.stream(
            {"messages": [("user", question)]},
            config={"recursion_limit": limit or recursion_limit(middleware)},
            context=CONTEXT,
            stream_mode="updates",
        ):
            for node, update in chunk.items():
                for msg in (update or {}).get("messages", []):
                    events.extend(translator.for_message(node, msg))
    return events, outcome


def _stages(events):
    return [e["data"]["stage"] for e in events if e["type"] == "status"]


class TestHappyPath:
    @pytest.fixture
    def result(self):
        model = FakeToolModel(
            responses=[_tool_call("select vehicleno from vehicles"), AIMessage(content="Two.")]
        )
        return _run(model, FakeConnector())

    def test_emits_every_stage_of_the_frozen_contract(self, result):
        events, _ = result
        assert _stages(events) == ["router", "sql_gen", "sql_guard", "db_exec", "answer"]

    def test_event_order_matches_the_contract(self, result):
        events, _ = result
        assert [e["type"] for e in events] == [
            "status",
            "status",
            "status",
            "sql",
            "status",
            "rows",
            "status",
            "token",
        ]

    def test_the_sql_reported_is_the_guarded_sql(self, result):
        events, _ = result
        sql = next(e for e in events if e["type"] == "sql")["data"]["sql"]
        assert sql.upper().startswith("SELECT") and "LIMIT" in sql.upper()

    def test_rows_carry_columns_and_truncation(self, result):
        events, _ = result
        rows = next(e for e in events if e["type"] == "rows")["data"]
        assert rows["columns"] == ["vehicleno"]
        assert rows["rows"] == [["KA01"], ["KA02"]]
        assert rows["truncated"] is False

    def test_the_outcome_records_what_the_run_row_needs(self, result):
        _, outcome = result
        assert outcome.tool == "sql"
        assert outcome.sql.upper().startswith("SELECT")
        assert len(outcome.rows) == 2
        assert outcome.answer == "Two."


class TestQuestionNeedingNoDatabase:
    def test_answers_without_touching_the_connector(self):
        model = FakeToolModel(responses=[AIMessage(content="I only answer data questions.")])
        connector = FakeConnector()
        events, outcome = _run(model, connector)

        assert _stages(events) == ["router", "answer"]
        assert outcome.tool == "clarify"
        assert outcome.sql is None
        assert connector.executed == []


class TestGuardRejection:
    def test_a_refused_query_is_retried_and_never_reaches_the_database(self):
        model = FakeToolModel(
            responses=[
                _tool_call("delete from vehicles"),
                _tool_call("select vehicleno from vehicles"),
                AIMessage(content="Two."),
            ]
        )
        connector = FakeConnector()
        events, outcome = _run(model, connector)

        assert _stages(events) == [
            "router",
            "sql_gen",
            "sql_guard",  # refused, so no sql or rows event
            "sql_gen",
            "sql_guard",
            "db_exec",
            "answer",
        ]
        assert len(connector.executed) == 1, "the refused statement reached the database"
        assert "DELETE" not in connector.executed[0].upper()
        assert outcome.answer == "Two."

    def test_the_refusal_is_reported_with_its_sql_and_reason_and_no_new_stage(self):
        model = FakeToolModel(
            responses=[_tool_call("delete from vehicles"), AIMessage(content="No.")]
        )
        events, _ = _run(model, FakeConnector())

        types = [e["type"] for e in events]
        rejected = events[types.index("rejected")]
        assert events[types.index("rejected") - 1]["data"] == {"stage": "sql_guard"}
        assert rejected["data"]["sql"] == "delete from vehicles"
        assert rejected["data"]["reason"] and rejected["data"]["at"] == "guard"
        assert _stages(events) == ["router", "sql_gen", "sql_guard", "answer"]


EXPLAINED = {"what": "Lists every vehicle.", "why": "You asked which vehicles there are."}


class TestTrace:
    """What a saved run shows of its steps. It must be what the stream said, or a run reloaded
    from history would tell a different story from the one watched live."""

    @pytest.fixture
    def result(self):
        model = FakeToolModel(
            responses=[
                _tool_call("delete from vehicles"),
                _tool_call("select vehicleno from vehicles", **EXPLAINED),
                AIMessage(content="Two."),
            ]
        )
        return _run(model, FakeConnector())

    def test_the_stages_are_exactly_the_ones_streamed(self, result):
        events, outcome = result
        assert outcome.stages == _stages(events)

    def test_each_query_tried_is_kept_with_its_outcome_and_no_rows(self, result):
        _, outcome = result
        refused, answered = outcome.attempts

        assert refused["rejected"] is True and refused["at"] == "guard"
        assert refused["sql"] == "delete from vehicles" and refused["reason"]
        assert answered["rejected"] is False
        assert answered["what"] == "Lists every vehicle."
        assert answered["why"] == "You asked which vehicles there are."
        assert answered["rows"] == 2 and answered["truncated"] is False
        assert isinstance(answered["ms"], int)
        assert "columns" not in answered, "a trace keeps counts, never the result"

    def test_the_sql_event_carries_the_explanation_and_rows_carry_the_time(self, result):
        events, _ = result
        sql = next(e for e in events if e["type"] == "sql")["data"]
        rows = next(e for e in events if e["type"] == "rows")["data"]
        assert sql["what"] == "Lists every vehicle." and sql["why"].startswith("You asked")
        assert isinstance(rows["ms"], int)

    def test_a_question_needing_no_query_tries_none(self):
        model = FakeToolModel(responses=[AIMessage(content="I only answer data questions.")])
        _, outcome = _run(model, FakeConnector())
        assert outcome.stages == ["router", "answer"]
        assert outcome.attempts == []


class TestRecursionLimit:
    """The limit counts supersteps, and middleware adds nodes. Pinned here because getting it
    wrong does not fail loudly - it reports that the model gave up."""

    def test_it_allows_one_more_superstep_than_a_full_run_takes(self):
        """LangGraph raises when the count reaches the limit, so a run needing N supersteps
        needs N + 1. Without this the last permitted tool call always failed."""
        calls = get_settings().max_tool_calls

        assert recursion_limit([]) == (2 * calls + 1) + 1

    def test_it_leaves_room_for_more_than_one_query(self):
        # A model may legitimately query twice to answer one question; the first limit was
        # derived from max_sql_retries and cut runs off after three tool calls.
        assert recursion_limit([]) >= 2 * 3 + 1

    def test_a_before_model_hook_widens_it_by_one_step_per_cycle(self):
        calls = get_settings().max_tool_calls
        # Summarisation hooks before_model, so every cycle costs three steps rather than two.
        assert recursion_limit(build_middleware(False)) == calls * 3 + 3

    def test_memory_adds_two_steps_to_the_run_and_none_to_the_cycle(self):
        # before_agent and after_agent run once each; the read is a wrap hook and adds no node.
        assert (
            recursion_limit(build_middleware(True)) == recursion_limit(build_middleware(False)) + 2
        )


class TestContentBlocks:
    """Gemini 3 returns a list of content blocks. Reading `.content` would put a Python repr
    of that list into the token event instead of the answer."""

    def test_the_answer_is_flattened_from_content_blocks(self):
        blocks = [{"type": "text", "text": "There are three dealers.", "extras": {"sig": "x"}}]
        model = FakeToolModel(responses=[AIMessage(content=blocks)])
        events, outcome = _run(model, FakeConnector())

        token = next(e for e in events if e["type"] == "token")
        assert token["data"]["text"] == "There are three dealers."
        assert outcome.answer == "There are three dealers."

    def test_a_plain_string_answer_still_works(self):
        model = FakeToolModel(responses=[AIMessage(content="Plain string.")])
        events, _ = _run(model, FakeConnector())
        assert next(e for e in events if e["type"] == "token")["data"]["text"] == "Plain string."


class TestChartEvent:
    """`chart` is a payload, not a stage. Adding a stage would break the frozen sequence and put
    a second copy of the decision into the web client's state machine."""

    def _chartable(self):
        model = FakeToolModel(
            responses=[
                _tool_call("select vehicleno, soc from vehicles"),
                AIMessage(content="West leads."),
            ]
        )
        connector = FakeConnector(rows=(("KA01", 82), ("KA02", 61)))
        connector.columns = ["vehicleno", "soc"]
        return _run(model, connector)

    def test_a_chartable_result_emits_a_chart_after_the_rows(self):
        events, outcome = self._chartable()
        types = [e["type"] for e in events]

        assert types.index("chart") == types.index("rows") + 1
        assert outcome.chart == {"type": "bar", "x": "vehicleno", "y": ["soc"]}

    def test_the_stage_sequence_is_unchanged(self):
        events, _ = self._chartable()

        assert _stages(events) == ["router", "sql_gen", "sql_guard", "db_exec", "answer"]

    def test_a_result_with_nothing_to_plot_emits_no_chart(self):
        model = FakeToolModel(
            responses=[_tool_call("select vehicleno from vehicles"), AIMessage(content="Two.")]
        )
        events, outcome = _run(model, FakeConnector())

        assert "chart" not in [e["type"] for e in events]
        assert outcome.chart is None

    def test_a_refused_query_emits_no_chart(self):
        model = FakeToolModel(
            responses=[_tool_call("delete from vehicles"), AIMessage(content="No.")]
        )
        events, _ = _run(model, FakeConnector())

        assert "chart" not in [e["type"] for e in events]


class TestTheWholeToolBudgetIsSpendable:
    """The arithmetic in `recursion_limit` is one thing; actually spending the budget is the
    thing it exists for. A limit that is too tight does not fail loudly - the customer is told
    the model gave up after too many query attempts, which is not what happened."""

    def _model_using_every_call(self):
        calls = get_settings().max_tool_calls
        return FakeToolModel(
            responses=[
                *[_tool_call("select vehicleno from vehicles") for _ in range(calls)],
                AIMessage(content="Done."),
            ]
        )

    def test_a_run_may_make_every_tool_call_it_is_allowed(self):
        connector = FakeConnector()

        _, outcome = _run(self._model_using_every_call(), connector, store=InMemoryStore())

        assert len(connector.executed) == get_settings().max_tool_calls
        assert outcome.answer == "Done."

    def test_the_bound_before_middleware_would_have_cut_it_short(self):
        """If this stops raising, the limit is no longer what makes the test above pass."""
        old_bound = 2 * get_settings().max_tool_calls + 1

        with pytest.raises(GraphRecursionError):
            _run(
                self._model_using_every_call(),
                FakeConnector(),
                store=InMemoryStore(),
                limit=old_bound,
            )


class FlatEngine:
    name = "flat"
    max_context = 1024
    max_horizon = 256

    def predict(self, values, horizon):
        mean = np.full(horizon, values[-1])
        return EngineForecast(mean=mean, lower=mean - 1, upper=mean + 1)


def _built_with(forecaster):
    with (
        patch("app.agent.graph.get_forecaster", return_value=forecaster),
        patch("app.agent.graph.create_agent") as create,
        patch("app.agent.graph.get_llm"),
    ):
        build_agent(FakeConnector(), CATALOG, middleware=[])
    kwargs = create.call_args.kwargs
    return kwargs["system_prompt"], [t.name for t in kwargs["tools"]]


class TestForecastingIsOfferedOnlyWhenLoaded:
    def test_off_the_prompt_says_so_and_no_tool_is_offered(self):
        prompt, tools = _built_with(None)

        assert FORECAST_OFF in prompt
        assert tools == ["query_database"]

    def test_on_the_prompt_explains_the_tool_that_is_offered(self):
        prompt, tools = _built_with(ForecastService(FlatEngine()))

        assert FORECAST_CAPABILITY in prompt
        assert "forecast_series" in tools


class ScriptedConnector:
    """Answers each query in turn with its own columns and rows."""

    kind = "postgres"
    dialect = "postgres"

    def __init__(self, *results):
        self.results = list(results)

    def run_select(self, sql, max_rows):
        columns, rows = self.results.pop(0)
        return columns, rows[:max_rows]


TWELVE_DAYS = [(f"2026-09-{d:02d}", 10 + d) for d in range(12, 0, -1)]


def _forecast_call(call_id="f1"):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "forecast_series",
                "args": {
                    "sql": "select day, n from vehicles order by day desc",
                    "time_column": "day", "value_column": "n",
                    "grain": "day", "horizon": 3, "kind": "total",
                },
                "id": call_id,
            }
        ],
    )  # fmt: skip


class TestAForecastRun:
    def _run(self, *responses, connector=None):
        connector = connector or ScriptedConnector((["day", "n"], TWELVE_DAYS))
        with patch("app.agent.graph.get_forecaster", return_value=ForecastService(FlatEngine())):
            return _run(FakeToolModel(responses=list(responses)), connector)

    def test_it_streams_the_same_stages_and_a_forecast_chart(self):
        events, outcome = self._run(_forecast_call(), AIMessage(content="About 22 a day."))

        assert _stages(events) == ["router", "sql_gen", "sql_guard", "db_exec", "answer"]
        types = [e["type"] for e in events]
        assert types.index("chart") == types.index("rows") + 1
        chart = next(e for e in events if e["type"] == "chart")["data"]
        assert chart["type"] == "forecast" and len(chart["forecast"]["points"]) == 3
        assert outcome.tool == "forecast"

    def test_a_later_query_clears_the_saved_chart_as_the_client_does(self):
        connector = ScriptedConnector(
            (["day", "n"], TWELVE_DAYS), (["vehicleno"], [("KA01",), ("KA02",)])
        )

        _, outcome = self._run(
            _forecast_call(),
            _tool_call("select vehicleno from vehicles"),
            AIMessage(content="Two."),
            connector=connector,
        )

        assert outcome.chart is None

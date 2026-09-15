"""Which source answers a question, and what happens when the model is no help.

The model call is patched out throughout. What is worth testing here is not whether Gemini can
tell "right now" from "last month" -- that belongs in the evals -- but that every answer it
could give, including a useless one, lands on a real connection.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.agent.router import HISTORIC, LIVE, choose_source, classify
from app.db.models import Connection


def conn(kind: str, *, cid: str = "", age_days: int = 0, deleted: bool = False) -> Connection:
    return Connection(
        id=cid or f"{kind}-{age_days}",
        tenant_id="t1",
        name=f"{kind} source",
        kind=kind,
        secret_enc="x",
        created_at=datetime.now(UTC) - timedelta(days=age_days),
        deleted_at=datetime.now(UTC) if deleted else None,
    )


class FakeReply:
    def __init__(self, text: str) -> None:
        self.text = text


def answering(text: str):
    """Patch the model to return one canned word."""
    model = type("M", (), {"invoke": lambda self, messages: FakeReply(text)})()
    return patch("app.agent.router.get_llm", return_value=model)


class TestClassify:
    @pytest.mark.parametrize("said", ["live", "Live", "LIVE", "live\n", "live."])
    def test_reads_live_however_it_is_spelled(self, said):
        with answering(said):
            assert classify("what is happening now") == LIVE

    @pytest.mark.parametrize("said", ["historic", "Historic", "historic\n"])
    def test_reads_historic(self, said):
        with answering(said):
            assert classify("totals for last month") == HISTORIC

    def test_a_word_it_was_not_offered_reads_as_historic(self):
        with answering("both, probably"):
            assert classify("anything") == HISTORIC

    def test_an_empty_answer_reads_as_historic(self):
        with answering(""):
            assert classify("anything") == HISTORIC

    # The database answers far more kinds of question than the dashboard, and cannot fail on a
    # cold browser session, so it is the safer end to fall off.
    def test_a_model_that_raises_reads_as_historic(self):
        def boom(self, messages):
            raise RuntimeError("the provider is down")

        model = type("M", (), {"invoke": boom})()
        with patch("app.agent.router.get_llm", return_value=model):
            assert classify("anything") == HISTORIC


class TestChooseSource:
    def test_live_goes_to_the_dashboard(self):
        sources = [conn("postgres"), conn("web")]
        with answering("live"):
            assert choose_source("what is it doing now", sources).connection.kind == "web"

    def test_historic_goes_to_the_database(self):
        sources = [conn("postgres"), conn("web")]
        with answering("historic"):
            assert choose_source("totals last month", sources).connection.kind == "postgres"

    # Nothing in the schema stops a tenant holding two of a kind, and `list_connections` has no
    # ORDER BY, so the tie has to break on something stable rather than on row order.
    def test_two_of_a_kind_break_the_tie_on_the_newest(self):
        old = conn("postgres", cid="old", age_days=10)
        new = conn("postgres", cid="new", age_days=1)
        with answering("historic"):
            assert choose_source("q", [old, new, conn("web")]).connection.id == "new"

    def test_a_single_source_is_used_without_asking_the_model(self):
        only = conn("postgres")
        model = type("M", (), {"invoke": lambda self, m: pytest.fail("should not be called")})()
        with patch("app.agent.router.get_llm", return_value=model):
            route = choose_source("anything at all", [only])
        assert route.connection is only
        assert route.reason == "only source"

    def test_deleted_connections_are_not_candidates(self):
        live_one = conn("postgres", cid="kept")
        with answering("live"):
            route = choose_source("now", [live_one, conn("web", cid="gone", deleted=True)])
        assert route.connection.id == "kept"

    # Asking for a kind the tenant does not have should answer from what exists rather than
    # refusing: a wrong-but-available source still beats an error on screen.
    def test_asking_for_a_kind_that_is_missing_falls_back(self):
        with answering("live"):
            route = choose_source("now", [conn("postgres", cid="a"), conn("postgres", cid="b")])
        assert route.connection.kind == "postgres"
        assert "no source of that kind" in route.reason

    def test_no_connections_at_all_is_the_caller_s_problem(self):
        with pytest.raises(ValueError):
            choose_source("q", [])

    def test_every_connection_deleted_is_the_same_as_none(self):
        with pytest.raises(ValueError):
            choose_source("q", [conn("postgres", deleted=True)])

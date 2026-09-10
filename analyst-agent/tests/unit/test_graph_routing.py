"""The graph's edge functions decide retries and dead ends, so they are tested directly."""

import pytest

from app.agent.graph import _after_exec, _after_guard, _after_router
from app.config import get_settings

MAX_RETRIES = get_settings().max_sql_retries


@pytest.mark.parametrize(
    ("tool", "expected"),
    [("sql", "sql_gen"), ("web", "web_tool"), ("clarify", "answer")],
)
def test_router_sends_each_tool_to_its_node(tool, expected):
    assert _after_router({"tool": tool}) == expected


class TestAfterGuard:
    def test_clean_sql_goes_to_execution(self):
        assert _after_guard({"guard_error": None}) == "db_exec"

    def test_a_rejection_within_the_cap_goes_back_for_a_rewrite(self):
        assert _after_guard({"guard_error": "nope", "retries": 1}) == "sql_gen"

    def test_a_rejection_at_the_cap_gives_up_and_answers(self):
        state = {"guard_error": "nope", "retries": MAX_RETRIES + 1}
        assert _after_guard(state) == "answer"


class TestAfterExec:
    def test_rows_go_to_the_answer(self):
        assert _after_exec({"guard_error": None}) == "answer"

    def test_a_database_error_within_the_cap_goes_back_for_a_rewrite(self):
        assert _after_exec({"guard_error": "database error", "retries": 0}) == "sql_gen"

    def test_a_database_error_at_the_cap_gives_up_and_answers(self):
        state = {"guard_error": "database error", "retries": MAX_RETRIES + 1}
        assert _after_exec(state) == "answer"


def test_the_retry_loop_terminates():
    """A rejection that keeps failing must reach `answer`, never loop forever."""
    retries, hops = 0, 0
    while _after_guard({"guard_error": "always bad", "retries": retries}) == "sql_gen":
        retries += 1
        hops += 1
        assert hops <= MAX_RETRIES + 2, "guard retry loop does not terminate"
    assert hops == MAX_RETRIES + 1

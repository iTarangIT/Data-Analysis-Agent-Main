"""What the agent carries between runs, and what it must never carry across a tenant."""

from langgraph.store.memory import InMemoryStore

from app.agent import memory
from app.agent.context import RunContext

CONTEXT = RunContext(tenant_id="t_one", connection_id="c1", run_id="r1", thread_id="th1")
SAME_TENANT_OTHER_CONNECTION = RunContext(
    tenant_id="t_one", connection_id="c2", run_id="r2", thread_id="th2"
)
OTHER_TENANT = RunContext(tenant_id="t_two", connection_id="c1", run_id="r3", thread_id="th3")


def store():
    return InMemoryStore()


class TestNothingRemembered:
    def test_a_connection_with_no_history_adds_nothing_to_the_prompt(self):
        assert memory.recall(store(), CONTEXT) == ""


class TestGlossary:
    def test_a_definition_comes_back_in_the_customers_own_wording(self):
        s = store()
        memory.remember_definition(s, CONTEXT, "net revenue", "sales minus refunds")

        assert "net revenue: sales minus refunds" in memory.recall(s, CONTEXT)

    def test_redefining_a_term_replaces_it_rather_than_stacking(self):
        s = store()
        memory.remember_definition(s, CONTEXT, "Net Revenue", "sales minus refunds")
        memory.remember_definition(s, CONTEXT, "net  revenue", "sales minus refunds and tax")

        recalled = memory.recall(s, CONTEXT)
        assert "sales minus refunds and tax" in recalled
        assert recalled.count("sales minus refunds") == 1, "the old definition survived"
        assert recalled.count("revenue") == 1, "case and spacing made a second entry"


class TestQueries:
    def test_a_query_that_answered_is_offered_as_a_worked_example(self):
        s = store()
        memory.remember_query(s, CONTEXT, "how many vehicles", "SELECT count(*) FROM vehicles")

        recalled = memory.recall(s, CONTEXT)
        assert "how many vehicles" in recalled and "count(*)" in recalled

    def test_asking_the_same_question_again_overwrites_rather_than_accumulates(self):
        s = store()
        memory.remember_query(s, CONTEXT, "how many vehicles", "SELECT 1")
        memory.remember_query(s, CONTEXT, "How many vehicles", "SELECT count(*) FROM vehicles")

        recalled = memory.recall(s, CONTEXT)
        assert "SELECT 1" not in recalled, "the superseded query is still being offered"
        assert "count(*)" in recalled


class TestCorrections:
    def test_a_refusal_recalls_the_query_that_worked_instead(self):
        s = store()
        memory.remember_correction(s, CONTEXT, "select * from secrets", "not allowed", "select 1")

        assert memory.recall_correction(s, CONTEXT, "select * from secrets")["corrected"] == (
            "select 1"
        )

    def test_a_query_never_refused_recalls_nothing(self):
        assert memory.recall_correction(store(), CONTEXT, "select 1") is None


class TestThreads:
    def test_a_thread_keeps_the_question_the_sql_and_the_answer(self):
        s = store()
        memory.remember_thread(s, CONTEXT, "how many", "SELECT 1", "Two.")

        kept = s.get(("t_one", memory.THREADS), "th1").value
        assert kept["question"] == "how many"
        assert kept["sql"] == "SELECT 1"
        assert kept["answer"] == "Two."

    def test_it_keeps_no_result_rows(self):
        """This database holds the structure of a customer's tables and never their contents."""
        s = store()
        memory.remember_thread(s, CONTEXT, "how many", "SELECT 1", "Two.")

        assert set(s.get(("t_one", memory.THREADS), "th1").value) == {
            "question",
            "sql",
            "answer",
            "at",
        }


class TestIsolation:
    def test_another_tenant_sees_none_of_it(self):
        s = store()
        memory.remember_definition(s, CONTEXT, "net revenue", "sales minus refunds")
        memory.remember_query(s, CONTEXT, "how many", "SELECT 1")
        memory.set_preference(s, CONTEXT, "currency", "INR")

        assert memory.recall(s, OTHER_TENANT) == ""

    def test_another_connection_of_the_same_tenant_sees_no_schema_specific_memory(self):
        """A definition or a proven join means nothing against a different schema."""
        s = store()
        memory.remember_definition(s, CONTEXT, "net revenue", "sales minus refunds")

        assert "net revenue" not in memory.recall(s, SAME_TENANT_OTHER_CONNECTION)

    def test_a_preference_follows_the_tenant_across_their_connections(self):
        s = store()
        memory.set_preference(s, CONTEXT, "currency", "INR")

        assert "currency: INR" in memory.recall(s, SAME_TENANT_OTHER_CONNECTION)

    def test_a_correction_is_not_recalled_for_another_tenant(self):
        s = store()
        memory.remember_correction(s, CONTEXT, "select * from secrets", "no", "select 1")

        assert memory.recall_correction(s, OTHER_TENANT, "select * from secrets") is None


class TestPreferences:
    def test_setting_a_second_preference_keeps_the_first(self):
        s = store()
        memory.set_preference(s, CONTEXT, "currency", "INR")
        memory.set_preference(s, CONTEXT, "chart", "bar")

        recalled = memory.recall(s, CONTEXT)
        assert "currency: INR" in recalled and "chart: bar" in recalled

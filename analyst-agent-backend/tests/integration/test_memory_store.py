"""Long-term memory against the real store in the App DB.

These use throwaway tenant ids rather than `clean_app_db`, because on a development machine the
App DB is the owner's real account. Nothing here touches a table Alembic owns: the store keeps
its own two, created by LangGraph.
"""

import uuid

import psycopg
import pytest

from app.agent import memory
from app.agent.context import RunContext
from app.agent.store import _dsn, open_store, setup_store
from app.config import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def postgres_backed(monkeypatch):
    """The suite runs with memory off; this file is the one that exercises the real store."""
    monkeypatch.setattr(get_settings(), "memory_backend", "postgres", raising=False)
    setup_store()


@pytest.fixture
def ctx():
    return RunContext(
        tenant_id=f"t_{uuid.uuid4().hex[:8]}",
        connection_id=f"c_{uuid.uuid4().hex[:8]}",
        run_id="r1",
        thread_id=f"th_{uuid.uuid4().hex[:8]}",
    )


class TestSetup:
    def test_it_creates_only_its_own_two_tables(self):
        with psycopg.connect(_dsn()) as conn:
            present = {
                r[0]
                for r in conn.execute(
                    "select tablename from pg_tables where schemaname = 'public'"
                ).fetchall()
            }

        assert {"store", "store_migrations"} <= present

    def test_it_needs_no_vector_extension(self):
        """No IndexConfig is configured, so `setup()` never touches pgvector. Requiring it would
        make a plain Postgres refuse to start the service."""
        with psycopg.connect(_dsn()) as conn:
            installed = {r[0] for r in conn.execute("select extname from pg_extension").fetchall()}

        assert "vector" not in installed

    def test_running_it_again_is_harmless(self):
        setup_store()


class TestItSurvivesTheConnection:
    def test_a_definition_written_in_one_run_is_read_in_the_next(self, ctx):
        with open_store() as store:
            memory.remember_definition(store, ctx, "net revenue", "sales minus refunds")

        with open_store() as store:
            assert "net revenue: sales minus refunds" in memory.recall(store, ctx)

    def test_a_thread_keeps_the_question_sql_and_answer_and_no_rows(self, ctx):
        with open_store() as store:
            memory.remember_thread(store, ctx, "how many vehicles", "SELECT 1", "Two.")

        with open_store() as store:
            kept = store.get((ctx.tenant_id, memory.THREADS), ctx.thread_id).value

        assert kept["question"] == "how many vehicles"
        assert set(kept) == {"question", "sql", "answer", "at"}

    def test_a_correction_is_recalled_by_the_query_that_was_refused(self, ctx):
        with open_store() as store:
            memory.remember_correction(
                store, ctx, "select * from secrets", "not allowed", "select 1 from vehicles"
            )

        with open_store() as store:
            fix = memory.recall_correction(store, ctx, "SELECT *  FROM secrets")

        assert fix["corrected"] == "select 1 from vehicles"


class TestTenantsCannotReadEachOther:
    def test_another_tenant_recalls_nothing(self, ctx):
        other = RunContext(
            tenant_id=f"t_{uuid.uuid4().hex[:8]}",
            connection_id=ctx.connection_id,
            run_id="r2",
            thread_id="th2",
        )

        with open_store() as store:
            memory.remember_definition(store, ctx, "churn", "no order in 90 days")
            memory.set_preference(store, ctx, "currency", "INR")

            assert memory.recall(store, other) == ""

    def test_another_connection_of_the_same_tenant_sees_no_schema_memory(self, ctx):
        sibling = RunContext(
            tenant_id=ctx.tenant_id,
            connection_id=f"c_{uuid.uuid4().hex[:8]}",
            run_id="r2",
            thread_id="th2",
        )

        with open_store() as store:
            memory.remember_query(store, ctx, "how many vehicles", "SELECT count(*) FROM vehicles")

            assert "how many vehicles" not in memory.recall(store, sibling)

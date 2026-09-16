"""Alembic must not manage the tables LangGraph creates for long-term memory.

This is the highest-consequence line in the memory work and the easiest to lose: `store` is a
plausible enough name that a migration dropping it would read as tidying up. Autogenerate is run
for real here rather than reasoned about, and the same comparison is run with the filter removed
so the guard is proved to be load-bearing rather than vacuously true.
"""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.agent.store import LANGGRAPH_TABLES, owned_by_alembic, setup_store
from app.config import get_settings
from app.db.models import Base
from app.db.session import _engine

pytestmark = pytest.mark.integration


def _include_object(object_, name, type_, reflected, compare_to):
    return owned_by_alembic(name, type_)


@pytest.fixture(autouse=True)
def store_tables_exist(monkeypatch):
    monkeypatch.setattr(get_settings(), "memory_backend", "postgres", raising=False)
    setup_store()


def _diff(include_object):
    with _engine.connect() as conn:
        context = MigrationContext.configure(
            conn, opts={"include_object": include_object, "compare_type": True}
        )
        return compare_metadata(context, Base.metadata)


def _dropped_tables(diffs):
    return {d[1].name for d in diffs if isinstance(d, tuple) and d[0] == "remove_table"}


class TestWithTheFilter:
    def test_autogenerate_proposes_nothing_at_all(self):
        """The App DB is at head, so anything here is a change nobody asked for."""
        assert _diff(_include_object) == []

    def test_neither_store_table_is_proposed_for_removal(self):
        assert _dropped_tables(_diff(_include_object)) & LANGGRAPH_TABLES == set()


class TestWithoutTheFilter:
    """If this ever stops failing, the filter is no longer the thing protecting the memory and
    the test above has quietly become meaningless."""

    def test_autogenerate_would_drop_every_store_table(self):
        assert _dropped_tables(_diff(None)) >= LANGGRAPH_TABLES

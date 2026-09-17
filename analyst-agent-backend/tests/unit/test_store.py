"""Choosing where long-term memory lives, and what happens when it is switched off."""

import pytest
from langgraph.store.memory import InMemoryStore

from app.agent import store as store_mod
from app.config import Settings, get_settings


@pytest.fixture
def backend(monkeypatch):
    def use(name):
        monkeypatch.setattr(get_settings(), "memory_backend", name, raising=False)

    return use


class TestSwitchedOff:
    def test_no_store_is_opened(self, backend):
        backend("off")
        with store_mod.open_store() as store:
            assert store is None

    def test_the_agent_is_told_there_is_nothing_to_remember_with(self, backend):
        backend("off")
        assert store_mod.memory_enabled() is False

    def test_setup_does_nothing(self, backend):
        """There are no tables to create, and it must not reach for the App DB to find that out."""
        backend("off")
        store_mod.setup_store()


class TestInMemory:
    def test_it_yields_a_real_store(self, backend):
        backend("memory")
        with store_mod.open_store() as store:
            assert isinstance(store, InMemoryStore)

    def test_it_is_the_same_store_on_the_next_run(self, backend):
        """Memory that did not outlive a single run would not be memory at all."""
        backend("memory")
        with store_mod.open_store() as first:
            first.put(("t_one", "glossary"), "k", {"term": "churn"})
        with store_mod.open_store() as second:
            assert second.get(("t_one", "glossary"), "k").value == {"term": "churn"}

    def test_memory_is_enabled(self, backend):
        backend("memory")
        assert store_mod.memory_enabled() is True

    def test_setup_creates_nothing(self, backend):
        backend("memory")
        store_mod.setup_store()


class TestPostgresIsTheDefault:
    def test_the_shipped_default_keeps_memory_in_the_app_db(self):
        assert Settings.model_fields["memory_backend"].default == "postgres"


class TestTheAppDbDsn:
    """`app_db_url` is a SQLAlchemy URL and carries a `+psycopg` driver suffix. psycopg parses
    the DSN itself and rejects that suffix, so the store would fail to open at boot."""

    def test_the_driver_suffix_is_stripped(self):
        assert store_mod._dsn().startswith("postgresql://")

    def test_the_rest_of_the_url_is_untouched(self):
        dsn = store_mod._dsn()
        original = str(get_settings().app_db_url)
        assert dsn.partition("://")[2] == original.partition("://")[2]


class TestAlembicIsToldToLeaveTheStoreAlone:
    """`store` is a plausible enough name that a migration dropping it would read as tidying
    up. `test_alembic_excludes_the_store.py` proves the filter is wired in and load-bearing;
    this is the cheap guard on what it decides."""

    @pytest.mark.parametrize("name", ["store", "store_migrations"])
    def test_a_langgraph_table_is_not_alembics_to_manage(self, name):
        assert store_mod.owned_by_alembic(name, "table") is False

    @pytest.mark.parametrize("name", ["runs", "tenants", "connections", "users"])
    def test_our_own_tables_stay_alembics(self, name):
        assert store_mod.owned_by_alembic(name, "table") is True

    def test_an_index_on_a_store_table_is_left_to_alembics_usual_handling(self):
        """Excluding the table already takes its indexes with it; filtering on name here would
        also catch an index of ours that happened to be called `store`."""
        assert store_mod.owned_by_alembic("store", "index") is True

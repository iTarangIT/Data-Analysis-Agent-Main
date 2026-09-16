"""Where long-term memory lives.

The store sits in the App DB, not the checkpoint DB. A checkpoint database is disposable - it can
be dropped to recover from a bad thread - which is the opposite of what memory needs. Its tables
are created by LangGraph rather than by Alembic, which is why `alembic/env.py` excludes them.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langgraph.store.postgres import PostgresStore

from app.config import get_settings

# LangGraph creates and migrates these. Alembic finds them in the App DB, finds them absent from
# Base.metadata, and writes a migration dropping them - which would drop every memory the agent
# has. `alembic/env.py` filters on this, and `test_store.py` pins it.
LANGGRAPH_TABLES = frozenset({"store", "store_migrations"})


def owned_by_alembic(name: str, type_: str) -> bool:
    """Whether autogenerate may act on a thing it reflected out of the App DB."""
    return not (type_ == "table" and name in LANGGRAPH_TABLES)


def _dsn() -> str:
    """The App DB URL as psycopg wants it.

    `app_db_url` carries SQLAlchemy's `+psycopg` driver suffix and psycopg cannot parse it;
    `checkpoint_db_url` has no suffix precisely because LangGraph opens that one directly.
    """
    scheme, _, rest = str(get_settings().app_db_url).partition("://")
    return f"{scheme.partition('+')[0]}://{rest}"


@lru_cache
def _in_memory() -> InMemoryStore:
    """One per process, so memory outlives a run the way the Postgres store does."""
    return InMemoryStore()


@contextmanager
def open_store() -> Iterator[BaseStore | None]:
    """The store for one run, or None when memory is off and no middleware should read it."""
    backend = get_settings().memory_backend
    if backend == "off":
        yield None
    elif backend == "memory":
        yield _in_memory()
    else:
        with PostgresStore.from_conn_string(_dsn()) as store:
            yield store


def setup_store() -> None:
    """Create the store's tables, once, at boot.

    `setup()` issues `CREATE INDEX CONCURRENTLY`, which cannot run inside a transaction, so it
    needs the autocommit connection `from_conn_string` opens and would fail on a borrowed
    SQLAlchemy one.
    """
    if get_settings().memory_backend != "postgres":
        return
    with PostgresStore.from_conn_string(_dsn()) as store:
        store.setup()


def memory_enabled() -> bool:
    return get_settings().memory_backend != "off"

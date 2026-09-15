from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.catalog.types import TableDef
from app.config import get_settings
from app.connectors import pg_catalog, pg_stats


class PostgresConnector:
    """Read-only access to one tenant's Postgres.

    The connection options repeat what the `analyst_ro` role already enforces. That redundancy
    is deliberate: it is the second of the three read-only layers, and it still holds if a
    customer hands us a role that was set up loosely.
    """

    kind = "postgres"
    dialect = "postgres"

    def __init__(self, dsn: str):
        s = get_settings()
        self.engine: Engine = create_engine(
            dsn,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=2,
            connect_args={
                # search_path is pinned so a bare table name can only mean the `public` table
                # the guard allowed, whatever the customer's role has set.
                "options": (
                    f"-c statement_timeout={s.statement_timeout_ms} "
                    "-c default_transaction_read_only=on "
                    "-c search_path=public"
                )
            },
        )

    def list_tables(self) -> list[str]:
        with self.engine.connect() as conn:
            return pg_catalog.list_tables(conn)

    def read_tables(self, names: list[str]) -> list[TableDef]:
        with self.engine.connect() as conn:
            return pg_catalog.read_tables(conn, names)

    def table_stats(self, names: list[str]) -> dict[str, dict[str, Any]]:
        """What each table holds: a size bucket and, for a time-partitioned table, how far its
        data runs. Catalog metadata rather than row contents, and without it the model cannot
        tell an empty table from a filter that matched nothing."""
        # A connection of its own: `collect` shortens the statement timeout for the rest of
        # whatever transaction it runs in.
        with self.engine.connect() as conn:
            return pg_stats.collect(conn, names)

    def run_select(self, sql: str, max_rows: int) -> tuple[list[str], list[tuple]]:
        with self.engine.connect() as conn:
            res = conn.execute(text(sql))
            cols = list(res.keys())
            rows = res.fetchmany(max_rows)
        return cols, [tuple(r) for r in rows]

    def test(self) -> bool:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT 1")).scalar() == 1

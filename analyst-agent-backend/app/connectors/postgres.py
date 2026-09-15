from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.catalog.types import TableDef
from app.config import get_settings
from app.connectors import pg_catalog, pg_stats

# Bumped when the shape of what `describe_schema` returns changes, so a cache written by an
# older build is refreshed rather than served for another six hours.
SCHEMA_VERSION = 2


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

    def describe_schema(self, sample_rows: int | None = None) -> dict[str, Any]:
        """Table and column names, used as the SQL generator's context and as the guard's
        table allowlist.

        Sample rows help the model see value formats, but they are real customer rows and end
        up in every generation prompt, so `schema_sample_rows` may switch them off entirely.

        Each table also carries what it holds: a size bucket and, where the table is
        partitioned by time, how far its data actually runs. That is catalog metadata rather
        than row contents, so it stands apart from `schema_sample_rows`, and without it the
        model cannot tell an empty table from a filter that matched nothing.
        """
        if sample_rows is None:
            sample_rows = get_settings().schema_sample_rows

        insp = inspect(self.engine)
        tables: list[dict[str, Any]] = []
        with self.engine.connect() as conn:
            names = pg_catalog.list_tables(conn)
            stats = pg_stats.collect(conn, names)
            for table in names:
                cols = [
                    {"name": c["name"], "type": str(c["type"])} for c in insp.get_columns(table)
                ]
                sample = []
                if sample_rows > 0:
                    rows = conn.execute(text(f'SELECT * FROM "{table}" LIMIT {sample_rows}'))
                    sample = [[str(v) for v in row] for row in rows]
                entry: dict[str, Any] = {"name": table, "columns": cols, "sample": sample}
                if table in stats:
                    entry["stats"] = stats[table]
                tables.append(entry)
        return {"v": SCHEMA_VERSION, "tables": tables}

    def list_tables(self) -> list[str]:
        with self.engine.connect() as conn:
            return pg_catalog.list_tables(conn)

    def read_tables(self, names: list[str]) -> list[TableDef]:
        with self.engine.connect() as conn:
            return pg_catalog.read_tables(conn, names)

    def table_stats(self, names: list[str]) -> dict[str, dict[str, Any]]:
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

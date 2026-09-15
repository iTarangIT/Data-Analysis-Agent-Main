from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.config import get_settings
from app.connectors import pg_stats

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
                "options": (
                    f"-c statement_timeout={s.statement_timeout_ms} "
                    f"-c default_transaction_read_only=on"
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
            names = self._visible_tables(conn)
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

    @staticmethod
    def _visible_tables(conn) -> list[str]:
        """Ordinary and partitioned tables in `public`, never partition children.

        `Inspector.get_table_names` returns children too. On the iTarang IoT database that is
        100 weekly partitions against 15 real tables, which would swamp the generator's prompt
        and let the guard accept a query aimed at one week's partition instead of the parent.
        Views are excluded with them: the only ones present belong to pg_stat_statements.
        """
        rows = conn.execute(
            text(
                """
                SELECT c.relname
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public'
                   AND c.relkind IN ('r', 'p')
                   AND NOT c.relispartition
                 ORDER BY c.relname
                """
            )
        )
        return [r[0] for r in rows]

    def run_select(self, sql: str, max_rows: int) -> tuple[list[str], list[tuple]]:
        with self.engine.connect() as conn:
            res = conn.execute(text(sql))
            cols = list(res.keys())
            rows = res.fetchmany(max_rows)
        return cols, [tuple(r) for r in rows]

    def test(self) -> bool:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT 1")).scalar() == 1

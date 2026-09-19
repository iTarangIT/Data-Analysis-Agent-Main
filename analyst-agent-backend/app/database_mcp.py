"""The database MCP server: the only process that opens a customer's database.

It runs on its own port, not inside the API, because it is the only thing that decrypts a
customer DSN. Everything the agent knows about a customer's Postgres arrives through the four
tools here, which are the `SqlConnector` protocol expressed over MCP.

All three of the read-only layers live here together: the `analyst_ro` role, the connection
options that repeat it, and the guard. `run_select` therefore guards on its own account rather
than trusting its caller - a server holding a decrypted DSN must not be a bare SQL proxy, even
though `app.agent.tools` guards before it calls.

Run it with `uvicorn app.database_mcp:app --port 8001`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from sqlalchemy import create_engine, make_url, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.agent.nodes.sql_guard import validate_sql
from app.catalog.types import TableDef
from app.config import get_settings
from app.connectors import pg_catalog, pg_stats
from app.db.models import Connection, ConnectionTable
from app.db.session import SessionLocal
from app.mcp_auth import ISSUER, MCPTokenVerifier
from app.security import vault


class QueryResult(BaseModel):
    """`error` travels as data, not as an exception: the reason is a retry hint the model reads
    and rewrites from, so it has to survive the trip back.

    Whether the result was truncated is left to the caller, which asks for one row more than it
    means to keep - the same contract the in-process connector had.
    """

    sql: str = ""
    columns: list[str] = []
    rows: list[list[Any]] = []
    error: str | None = None


class CustomerDatabase:
    """One customer's Postgres, opened read-only.

    The connection options repeat what the `analyst_ro` role already enforces. That redundancy
    is deliberate: it is the second of the three read-only layers, and it still holds if a
    customer hands us a role that was set up loosely.
    """

    def __init__(self, dsn: str):
        s = get_settings()
        self.engine: Engine = create_engine(
            # `postgresql://` means psycopg2 to SQLAlchemy, and only psycopg is installed.
            make_url(dsn).set(drivername="postgresql+psycopg"),
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=2,
            connect_args={
                "connect_timeout": s.connect_timeout_s,
                # search_path is pinned so a bare table name can only mean the `public` table
                # the guard allowed, whatever the customer's role has set.
                "options": (
                    f"-c statement_timeout={s.statement_timeout_ms} "
                    "-c default_transaction_read_only=on "
                    "-c search_path=public"
                ),
            },
        )

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

    def run_select(self, sql: str, fetch: int, allowed: set[str]) -> QueryResult:
        """`fetch` is how many rows to read back; the row cap the statement is rewritten with is
        this server's own setting, never a number the caller chose."""
        safe_sql, error = validate_sql(sql, allowed, get_settings().max_rows, "postgres")
        if error:
            return QueryResult(error=error)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(safe_sql))
                columns = list(result.keys())
                rows = result.fetchmany(fetch)
        except Exception as exc:
            return QueryResult(error=f"database error: {exc}")
        return QueryResult(sql=safe_sql, columns=columns, rows=[list(r) for r in rows])

    def close(self) -> None:
        self.engine.dispose()


def _claims() -> tuple[str, str]:
    """Which customer database this call is for, taken only from the verified token.

    Nothing in a tool's arguments names a connection, so a caller cannot reach a database by
    asking for it: it can only reach the one its token was minted for.
    """
    token: AccessToken | None = get_access_token()
    claims = token.claims if token else None
    tenant_id = claims.get("tenant_id") if claims else None
    connection_id = claims.get("connection_id") if claims else None
    if not tenant_id or not connection_id:
        raise ValueError("database context is missing")
    return tenant_id, connection_id


@contextmanager
def _database() -> Iterator[tuple[Session, Connection, CustomerDatabase]]:
    tenant_id, connection_id = _claims()
    db = SessionLocal()
    database: CustomerDatabase | None = None
    try:
        connection = db.get(Connection, connection_id)
        if (
            connection is None
            or connection.tenant_id != tenant_id
            or connection.deleted_at is not None
            or connection.kind != "postgres"
        ):
            raise ValueError("connection not found")
        database = CustomerDatabase(vault.decrypt(connection.secret_enc)["dsn"])
        yield db, connection, database
    finally:
        if database is not None:
            database.close()
        db.close()


settings = get_settings()
mcp = FastMCP(
    "Analyst Database",
    instructions="Read-only Postgres structure discovery and query execution.",
    token_verifier=MCPTokenVerifier(),
    auth=AuthSettings(
        issuer_url=ISSUER,
        resource_server_url=settings.database_mcp_url,
        required_scopes=["database:read"],
        validate_token_resource=True,
    ),
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
def list_tables() -> list[str]:
    """Every table this connection's database exposes, never partition children."""
    with _database() as (_, _, database):
        return database.list_tables()


@mcp.tool()
def read_tables(names: list[str]) -> list[TableDef]:
    """The structure of the named tables: columns, keys and constraints, never rows."""
    with _database() as (_, _, database):
        return database.read_tables(names)


@mcp.tool()
def table_stats(names: list[str]) -> dict[str, dict[str, Any]]:
    """What each named table holds: a size bucket and, for a partitioned table, its coverage."""
    with _database() as (_, _, database):
        return database.table_stats(names)


@mcp.tool()
def run_select(sql: str, max_rows: int) -> QueryResult:
    """Run one read-only SELECT over the tables chosen for this connection."""
    with _database() as (db, connection, database):
        # Re-read per query rather than cached: unselecting a table has to take effect now, not
        # when some session happens to end.
        allowed = set(
            db.scalars(
                select(ConnectionTable.name).where(
                    ConnectionTable.connection_id == connection.id,
                    ConnectionTable.selected.is_(True),
                )
            )
        )
        return database.run_select(sql, min(max_rows, get_settings().max_rows + 1), allowed)


app = mcp.streamable_http_app()

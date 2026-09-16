from app.connectors.base import Connector
from app.connectors.duckdb import DuckDBConnector, FileSource
from app.connectors.mcp import McpConnector
from app.db.models import Connection
from app.security import vault


def connector_for(conn: Connection) -> Connector:
    """Build the tenant's connector.

    A Postgres database is reached through the MCP server, which holds the credential and opens
    the connection itself, so nothing is decrypted here for one. `vault.decrypt` survives for
    file sources, whose paths this process does own.
    """
    if conn.kind == "postgres":
        return McpConnector(conn.tenant_id, conn.id)
    if conn.kind == "file":
        secret = vault.decrypt(conn.secret_enc)
        return DuckDBConnector(conn.tenant_id, [FileSource(**s) for s in secret["sources"]])
    raise ValueError(f"unsupported connection kind {conn.kind}")

from app.connectors import storage
from app.connectors.base import Connector
from app.connectors.duckdb import DuckDBConnector, FileSource
from app.connectors.mcp import McpConnector
from app.db.models import Connection


def connector_for(conn: Connection) -> Connector:
    """Build the tenant's connector.

    A Postgres database is reached through the MCP server, which holds the credential and opens
    the connection itself, so nothing is decrypted here for one.
    """
    if conn.kind == "postgres":
        return McpConnector(conn.tenant_id, conn.id)
    if conn.kind == "file":
        return DuckDBConnector(
            conn.tenant_id,
            [
                FileSource(
                    table=part["table"],
                    path=str(storage.local(part["storage_key"], part["sha256"])),
                    file=file.name,
                    origin=file.source.origin,
                    profile=part["profile"],
                    sheet=part["sheet"],
                )
                for file in conn.files
                if file.status == "ready"
                for part in file.parts
            ],
        )
    raise ValueError(f"unsupported connection kind {conn.kind}")

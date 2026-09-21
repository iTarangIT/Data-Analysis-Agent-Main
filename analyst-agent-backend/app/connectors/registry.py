from app.connectors.base import SqlConnector
from app.connectors.duckdb import Dataset, Part
from app.connectors.mcp import McpConnector
from app.db.models import Connection


def connector_for(conn: Connection) -> McpConnector | Dataset:
    """Build the tenant's connector.

    A Postgres database is reached through the MCP server, which holds the credential and opens
    the connection itself, so nothing is decrypted here for one.
    """
    if conn.kind == "postgres":
        return McpConnector(conn.tenant_id, conn.id)
    if conn.kind == "file":
        return Dataset(
            conn.tenant_id,
            [
                Part(
                    table=part["table"],
                    file=file.name,
                    origin=file.source.origin,
                    storage_key=part["storage_key"],
                    sha256=part["sha256"],
                    profile=part["profile"],
                    sheet=part["sheet"],
                )
                for file in conn.files
                if file.status == "ready"
                for part in file.parts
            ],
        )
    raise ValueError(f"unsupported connection kind {conn.kind}")


def open_for_run(reader: McpConnector | Dataset, tables: set[str]) -> SqlConnector:
    return reader.open(tables) if isinstance(reader, Dataset) else reader

from app.connectors.base import Connector
from app.connectors.postgres import PostgresConnector
from app.db.models import Connection
from app.security import vault


def connector_for(conn: Connection) -> Connector:
    """Build the tenant's connector. The only place `vault.decrypt` is called."""
    secret = vault.decrypt(conn.secret_enc)
    if conn.kind == "postgres":
        return PostgresConnector(secret["dsn"])
    raise ValueError(f"unsupported connection kind {conn.kind}")

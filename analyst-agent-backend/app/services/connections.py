from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.connectors.postgres import PostgresConnector
from app.db.models import Connection, Tenant
from app.logging import log
from app.security import vault
from app.services.errors import DomainError, NotFound


def ensure_tenant(db: Session, tenant_id: str) -> Tenant:
    """Tenants originate in analyst-web; this service only ever learns of one from a JWT."""
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        tenant = Tenant(id=tenant_id, name=tenant_id)
        db.add(tenant)
        db.commit()
    return tenant


def create_connection(
    db: Session, tenant_id: str, name: str, kind: str, secret: dict
) -> Connection:
    ensure_tenant(db, tenant_id)
    if kind == "postgres":
        try:
            PostgresConnector(secret["dsn"]).test()
        except SQLAlchemyError as e:
            # The driver's message quotes host, port and user, so it is logged rather than
            # returned. Storing a credential we cannot use only fails later, in a run.
            log.warning("connection.test_failed", kind=kind, error=str(e))
            raise DomainError("could not connect to that database with the details given") from e

    conn = Connection(tenant_id=tenant_id, name=name, kind=kind, secret_enc=vault.encrypt(secret))
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def list_connections(db: Session, tenant_id: str) -> list[Connection]:
    return db.query(Connection).filter(Connection.tenant_id == tenant_id).all()


def get_connection(db: Session, tenant_id: str, connection_id: str) -> Connection:
    conn = db.get(Connection, connection_id)
    if conn is None or conn.tenant_id != tenant_id:
        raise NotFound("connection not found")  # 404 for both, so existence does not leak
    return conn

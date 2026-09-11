import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors.duckdb import ingest_upload
from app.connectors.postgres import PostgresConnector
from app.db.models import Connection, Tenant
from app.logging import log
from app.security import vault
from app.services.errors import DomainError, NotFound


def ensure_tenant(db: Session, tenant_id: str) -> Tenant:
    """Adopt a tenant named by a JWT that has no row yet.

    Signing up creates the tenant now, so this is no longer how tenants normally appear. It
    stays for hand-minted tokens: the eval harness and the test fixtures both sign a
    tenant_id that was never registered, and every route they exercise depends on this.
    """
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
    return (
        db.query(Connection)
        .filter(Connection.tenant_id == tenant_id, Connection.deleted_at.is_(None))
        .all()
    )


def get_connection(db: Session, tenant_id: str, connection_id: str) -> Connection:
    conn = db.get(Connection, connection_id)
    if conn is None or conn.tenant_id != tenant_id or conn.deleted_at is not None:
        raise NotFound("connection not found")  # 404 for both, so existence does not leak
    return conn


def delete_connection(db: Session, tenant_id: str, connection_id: str) -> None:
    """Retire a connection and destroy the credential it held.

    Soft, because `runs.connection_id` references this row and runs are the ledger we price
    from; cascading would delete a tenant's billing history along with a tidied-up list. A
    deleted row therefore survives so history can still name the source, but it keeps nothing
    sensitive: "delete this connection" has to mean the customer's password is gone.

    Blanking `secret_enc` makes the row unusable rather than merely hidden, which is why
    `get_connection` rejects it before `connector_for` is ever reached.
    """
    conn = get_connection(db, tenant_id, connection_id)

    if conn.kind == "file":
        # Otherwise the customer's "deleted" spreadsheet stays readable on disk.
        shutil.rmtree(Path(get_settings().file_store_dir) / tenant_id / conn.id, ignore_errors=True)

    conn.deleted_at = datetime.now(UTC)
    conn.secret_enc = ""
    conn.schema_cache = None
    conn.schema_cached_at = None
    db.commit()
    log.info("connection.deleted", connection_id=conn.id, kind=conn.kind)


def create_file_connection(
    db: Session, tenant_id: str, name: str, upload: Path, filename: str
) -> Connection:
    """Register an uploaded file as a connection.

    The id is minted up front so the file lands in its final directory, rather than being
    written once and moved after an insert. The stored paths are server-side values the client
    never supplies, which is why there is no `kind="file"` on the create-connection body: a
    client-named path would be an arbitrary-file-read primitive that no SQL guard could catch.
    """
    ensure_tenant(db, tenant_id)
    connection_id = str(uuid.uuid4())
    dest = Path(get_settings().file_store_dir) / tenant_id / connection_id
    try:
        sources = ingest_upload(upload, dest, filename)
    except DomainError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(dest, ignore_errors=True)
        log.warning("upload.ingest_failed", error=str(e))
        raise DomainError("that file could not be read as a spreadsheet") from e

    secret = {
        "sources": [{"table": s.table, "path": s.path} for s in sources],
        "filename": filename,
    }
    conn = Connection(
        id=connection_id,
        tenant_id=tenant_id,
        name=name,
        kind="file",
        secret_enc=vault.encrypt(secret),
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn

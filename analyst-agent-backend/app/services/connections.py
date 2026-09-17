import shutil
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors.duckdb import FileSource, ingest_upload
from app.connectors.registry import file_sources
from app.db.models import Connection, Tenant
from app.logging import log
from app.security import vault
from app.services import tables
from app.services.errors import DomainError, NotFound


def ensure_tenant(db: Session, tenant_id: str) -> Tenant:
    """The tenant row for `tenant_id`, created if it is missing.

    A request's tenant always exists, since `current_tenant` resolves it from an account that
    references it. This stays for tests that seed runs and connections for a tenant directly.
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
    conn = Connection(tenant_id=tenant_id, name=name, kind=kind, secret_enc=vault.encrypt(secret))
    db.add(conn)
    db.commit()
    db.refresh(conn)

    # Listing the source is the connectivity proof. A Postgres database is only reachable
    # through MCP, which resolves a connection by id, so there is nothing to test before the row
    # exists - and a row whose source we cannot read is worse than no row at all.
    try:
        tables.ensure_listed(db, conn)
    except Exception as e:
        db.rollback()
        db.delete(conn)
        db.commit()
        # The driver's message quotes host, port and user, so it is logged rather than returned.
        log.warning("connection.listing_failed", kind=kind, error=str(e))
        raise DomainError("could not connect to that database with the details given") from e
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
    tables.forget(db, conn)
    db.commit()
    log.info("connection.deleted", connection_id=conn.id, kind=conn.kind)


def _ingest_batch(
    tenant_id: str, connection_id: str, uploads: list[tuple[Path, str]], existing: list[dict]
) -> list[dict]:
    names = [s["file"] for s in existing] + [filename for _, filename in uploads]
    repeated = sorted(name for name, count in Counter(names).items() if count > 1)
    if repeated:
        raise DomainError(f"a dataset cannot hold two files named {', '.join(repeated)}")

    settings = get_settings()
    batch = Path(settings.file_store_dir) / tenant_id / connection_id / uuid.uuid4().hex
    taken = {s["table"] for s in existing}
    added: list[FileSource] = []
    try:
        for src, filename in uploads:
            added += ingest_upload(src, batch, filename, taken)
        sources = existing + [asdict(s) for s in added]
        if sum(Path(s["path"]).stat().st_size for s in sources) > settings.max_dataset_bytes:
            raise DomainError(
                f"a dataset is limited to {settings.max_dataset_bytes} bytes once converted, "
                "and these files would take it past that"
            )
    except DomainError:
        shutil.rmtree(batch if existing else batch.parent, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(batch if existing else batch.parent, ignore_errors=True)
        log.warning("upload.ingest_failed", file=filename, error=str(e))
        raise DomainError(f"{filename} could not be read as a spreadsheet") from e
    return sources


def create_file_connection(
    db: Session, tenant_id: str, name: str, uploads: list[tuple[Path, str]]
) -> Connection:
    """Register an uploaded file as a connection.

    The id is minted up front so the file lands in its final directory, rather than being
    written once and moved after an insert. The stored paths are server-side values the client
    never supplies, which is why there is no `kind="file"` on the create-connection body: a
    client-named path would be an arbitrary-file-read primitive that no SQL guard could catch.
    """
    ensure_tenant(db, tenant_id)
    connection_id = str(uuid.uuid4())
    sources = _ingest_batch(tenant_id, connection_id, uploads, [])
    conn = Connection(
        id=connection_id,
        tenant_id=tenant_id,
        name=name,
        kind="file",
        secret_enc=vault.encrypt({"sources": sources}),
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    tables.ensure_listed(db, conn)
    return conn


def add_files(db: Session, conn: Connection, uploads: list[tuple[Path, str]]) -> dict[str, Any]:
    if conn.kind != "file":
        raise DomainError("only an uploaded dataset holds files")
    db.refresh(conn, with_for_update=True)
    sources = _ingest_batch(conn.tenant_id, conn.id, uploads, file_sources(conn))
    conn.secret_enc = vault.encrypt({"sources": sources})
    db.commit()
    return tables.refresh(db, conn)


def remove_file(db: Session, conn: Connection, filename: str) -> dict[str, Any]:
    if conn.kind != "file":
        raise DomainError("only an uploaded dataset holds files")
    db.refresh(conn, with_for_update=True)
    sources = file_sources(conn)
    kept = [s for s in sources if s["file"] != filename]
    if len(kept) == len(sources):
        raise NotFound(f"this dataset has no file named {filename}")
    if not kept:
        raise DomainError("a dataset needs at least one file - delete the connection instead")
    conn.secret_enc = vault.encrypt({"sources": kept})
    db.commit()

    removed = [Path(s["path"]) for s in sources if s["file"] == filename]
    for path in removed:
        path.unlink(missing_ok=True)
    for batch in {p.parent for p in removed} - {Path(s["path"]).parent for s in kept}:
        batch.rmdir()
    return tables.refresh(db, conn)

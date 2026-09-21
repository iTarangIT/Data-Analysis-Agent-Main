import hashlib
import shutil
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors import storage
from app.connectors.duckdb import FileSource, ingest_upload
from app.connectors.sandbox import Sandbox
from app.db.models import Connection, DatasetFile, DatasetSource, Tenant
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
        storage.delete([part for f in conn.files for part in f.parts])
        shutil.rmtree(Path(get_settings().file_store_dir) / tenant_id / conn.id, ignore_errors=True)
        db.execute(delete(DatasetFile).where(DatasetFile.connection_id == conn.id))
        db.execute(delete(DatasetSource).where(DatasetSource.connection_id == conn.id))

    conn.deleted_at = datetime.now(UTC)
    conn.secret_enc = ""
    tables.forget(db, conn)
    db.commit()
    log.info("connection.deleted", connection_id=conn.id, kind=conn.kind)


def file_counts(db: Session, connection_ids: list[str]) -> dict[str, int]:
    return dict(
        db.execute(
            select(DatasetFile.connection_id, func.count())
            .where(DatasetFile.connection_id.in_(connection_ids), DatasetFile.status == "ready")
            .group_by(DatasetFile.connection_id)
        )
        .tuples()
        .all()
    )


def _upload_source(db: Session, conn: Connection) -> DatasetSource:
    return db.scalars(
        select(DatasetSource).where(
            DatasetSource.connection_id == conn.id, DatasetSource.origin == "upload"
        )
    ).one()


def _store(tenant_id: str, connection_id: str, file_id: str, source: FileSource) -> dict:
    path = Path(source.path)
    with path.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    key = f"{tenant_id}/{connection_id}/{file_id}/{source.table}-{digest[:12]}.parquet"
    size = path.stat().st_size
    storage.put(path, key, digest)
    return {
        "sheet": source.sheet,
        "table": source.table,
        "storage_key": key,
        "sha256": digest,
        "bytes": size,
        "profile": source.profile,
    }


def _discard(tenant_id: str, connection_id: str, file: DatasetFile) -> None:
    storage.delete(file.parts)
    shutil.rmtree(
        Path(get_settings().file_store_dir) / tenant_id / connection_id / file.id,
        ignore_errors=True,
    )


def _ingest_batch(
    tenant_id: str,
    connection_id: str,
    source_id: str,
    uploads: list[tuple[Path, str]],
    held: list[DatasetFile],
) -> list[DatasetFile]:
    names = [f.name for f in held if f.source_id == source_id and f.status != "failed"]
    names += [filename for _, filename in uploads]
    repeated = sorted(name for name, count in Counter(names).items() if count > 1)
    if repeated:
        raise DomainError(f"a dataset cannot hold two files named {', '.join(repeated)}")

    settings = get_settings()
    root = Path(settings.file_store_dir) / tenant_id / connection_id
    taken = {part["table"] for f in held for part in f.parts}
    staged: list[tuple[str, str, int, list[FileSource]]] = []
    dirs: list[Path] = []
    stored: list[dict] = []
    try:
        with Sandbox() as sandbox:
            for src, filename in uploads:
                file_id = str(uuid.uuid4())
                dirs.append(root / file_id)
                sources = sandbox.run(filename, ingest_upload, src, root / file_id, filename, taken)
                taken |= {s.table for s in sources}
                staged.append((file_id, filename, src.stat().st_size, sources))
        held_bytes = sum(part["bytes"] for f in held for part in f.parts)
        added = sum(Path(s.path).stat().st_size for *_, sources in staged for s in sources)
        if held_bytes + added > settings.max_dataset_bytes:
            raise DomainError(
                f"a dataset is limited to {settings.max_dataset_bytes} bytes once converted, "
                "and these files would take it past that"
            )
        files = []
        for file_id, filename, size, sources in staged:
            parts = []
            for source in sources:
                parts.append(_store(tenant_id, connection_id, file_id, source))
                stored.append(parts[-1])
            files.append(
                DatasetFile(
                    id=file_id,
                    source_id=source_id,
                    connection_id=connection_id,
                    remote_id=filename,
                    name=filename,
                    status="ready",
                    bytes=size,
                    parts=parts,
                    synced_at=datetime.now(UTC),
                )
            )
    except DomainError:
        _undo(stored, dirs if held else [root])
        raise
    except Exception as e:
        _undo(stored, dirs if held else [root])
        log.warning("upload.ingest_failed", file=filename, error=str(e))
        raise DomainError(f"{filename} could not be read as a spreadsheet") from e

    for path in dirs:
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return files


def _undo(stored: list[dict], dirs: list[Path]) -> None:
    for path in dirs:
        shutil.rmtree(path, ignore_errors=True)
    storage.delete(stored)


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
    source_id = str(uuid.uuid4())
    uploaded = _ingest_batch(tenant_id, connection_id, source_id, uploads, [])
    conn = Connection(
        id=connection_id,
        tenant_id=tenant_id,
        name=name,
        kind="file",
        secret_enc=vault.encrypt({}),
    )
    db.add(conn)
    db.flush()
    db.add(
        DatasetSource(
            id=source_id,
            connection_id=connection_id,
            origin="upload",
            label="Uploads",
            status="active",
        )
    )
    db.flush()
    db.add_all(uploaded)
    db.commit()
    db.refresh(conn)
    tables.ensure_listed(db, conn)
    return conn


def create_dataset(db: Session, tenant_id: str, name: str) -> Connection:
    ensure_tenant(db, tenant_id)
    conn = Connection(tenant_id=tenant_id, name=name, kind="file", secret_enc=vault.encrypt({}))
    db.add(conn)
    db.flush()
    db.add(DatasetSource(connection_id=conn.id, origin="upload", label="Uploads", status="active"))
    db.commit()
    db.refresh(conn)
    return conn


def add_files(db: Session, conn: Connection, uploads: list[tuple[Path, str]]) -> dict[str, Any]:
    if conn.kind != "file":
        raise DomainError("only an uploaded dataset holds files")
    db.refresh(conn, with_for_update=True)
    source = _upload_source(db, conn)
    held = list(conn.files)
    uploaded = _ingest_batch(conn.tenant_id, conn.id, source.id, uploads, held)
    names = {f.name for f in uploaded}
    for f in held:
        if f.source_id == source.id and f.status == "failed" and f.name in names:
            db.delete(f)
    db.flush()
    db.add_all(uploaded)
    db.commit()
    db.expire(conn, ["files"])
    return tables.refresh(db, conn)


def remove_file(db: Session, conn: Connection, filename: str) -> dict[str, Any]:
    if conn.kind != "file":
        raise DomainError("only an uploaded dataset holds files")
    db.refresh(conn, with_for_update=True)
    source = _upload_source(db, conn)
    held = list(conn.files)
    found = next((f for f in held if f.source_id == source.id and f.remote_id == filename), None)
    if found is None:
        raise NotFound(f"this dataset has no file named {filename}")
    if found.status == "ready" and sum(f.status == "ready" for f in held) == 1:
        raise DomainError("a dataset needs at least one file - delete the connection instead")
    db.delete(found)
    db.commit()
    db.expire(conn, ["files"])
    _discard(conn.tenant_id, conn.id, found)
    return tables.refresh(db, conn)

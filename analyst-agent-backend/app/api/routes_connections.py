import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import current_tenant
from app.api.schemas import (
    MAX_UPLOAD_FILES,
    UPLOAD_SUFFIXES,
    ConnectionCreate,
    ConnectionOut,
    DatasetCreate,
    GoogleLink,
    ResolveOut,
    TableSelection,
    TablesOut,
    TablesRefreshOut,
)
from app.config import get_settings
from app.db.models import Connection
from app.db.session import get_db
from app.security.auth import TenantContext
from app.services import connections as svc
from app.services import sources as sources_svc
from app.services import tables as tables_svc

router = APIRouter()

Uploads = Annotated[list[UploadFile], File(min_length=1, max_length=MAX_UPLOAD_FILES)]


def _out(c: Connection, counts: dict[str, tuple[int, int]], files: dict[str, int]) -> ConnectionOut:
    selected, total = counts.get(c.id, (0, 0))
    return ConnectionOut(
        id=c.id,
        name=c.name,
        kind=c.kind,
        selected_tables=selected,
        total_tables=total,
        file_count=files.get(c.id, 0),
        catalog_refreshed_at=c.catalog_refreshed_at,
        sync_status=c.sync_status,
        synced_at=c.synced_at,
    )


@contextmanager
def _staged(files: list[UploadFile]) -> Iterator[list[tuple[Path, str]]]:
    limit = get_settings().max_upload_bytes
    staged: list[tuple[Path, str]] = []
    try:
        for file in files:
            filename = file.filename or ""
            suffix = Path(filename).suffix.lower()
            if suffix not in UPLOAD_SUFFIXES:
                raise HTTPException(415, f"{filename}: upload one of {sorted(UPLOAD_SUFFIXES)}")
            fd, staged_name = tempfile.mkstemp(suffix=suffix)
            staged.append((Path(staged_name), filename))
            written = 0
            # Closed before the finally unlinks it: Windows refuses to delete an open file.
            with os.fdopen(fd, "wb") as out:
                while chunk := file.file.read(1024 * 1024):
                    written += len(chunk)
                    if written > limit:
                        # content-length is client-controlled, so the running total is the guard.
                        raise HTTPException(
                            413, f"{filename}: uploads are limited to {limit} bytes"
                        )
                    out.write(chunk)
        yield staged
    finally:
        for path, _ in staged:
            path.unlink(missing_ok=True)


@router.post("", response_model=ConnectionOut, status_code=201)
def create(
    body: ConnectionCreate,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    conn = svc.create_connection(db, ctx.tenant_id, body.name, body.kind, body.secret)
    return _out(conn, tables_svc.counts(db, [conn.id]), svc.file_counts(db, [conn.id]))


@router.get("", response_model=list[ConnectionOut])
def list_(
    ctx: TenantContext = Depends(current_tenant), db: Session = Depends(get_db)
) -> list[ConnectionOut]:
    connections = svc.list_connections(db, ctx.tenant_id)
    ids = [c.id for c in connections]
    counts, files = tables_svc.counts(db, ids), svc.file_counts(db, ids)
    return [_out(c, counts, files) for c in connections]


@router.post("/file", response_model=ConnectionOut, status_code=201)
def create_from_file(
    files: Uploads,
    name: Annotated[str, Form(min_length=1, max_length=200)],
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> ConnectionOut:

    with _staged(files) as uploads:
        conn = svc.create_file_connection(db, ctx.tenant_id, name, uploads)
    return _out(conn, tables_svc.counts(db, [conn.id]), svc.file_counts(db, [conn.id]))


@router.post("/dataset", response_model=ConnectionOut, status_code=201)
def create_dataset(
    body: DatasetCreate,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    conn = svc.create_dataset(db, ctx.tenant_id, body.name)
    return _out(conn, tables_svc.counts(db, [conn.id]), svc.file_counts(db, [conn.id]))


@router.post("/{connection_id}/google/resolve", response_model=ResolveOut)
def resolve_google_link(
    connection_id: str,
    body: GoogleLink,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> ResolveOut:
    conn = svc.get_connection(db, ctx.tenant_id, connection_id)
    return ResolveOut.model_validate(
        sources_svc.resolve(db, conn, ctx.user_id, body.url, body.confirm_unverified)
    )


@router.post("/{connection_id}/files", response_model=TablesOut)
def add_files(
    connection_id: str,
    files: Uploads,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> TablesOut:
    conn = svc.get_connection(db, ctx.tenant_id, connection_id)
    with _staged(files) as uploads:
        return TablesOut.model_validate(svc.add_files(db, conn, uploads))


@router.delete("/{connection_id}/files/{filename}", response_model=TablesOut)
def remove_file(
    connection_id: str,
    filename: str,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> TablesOut:
    conn = svc.get_connection(db, ctx.tenant_id, connection_id)
    return TablesOut.model_validate(svc.remove_file(db, conn, filename))


@router.get("/{connection_id}/tables", response_model=TablesOut)
def read_tables(
    connection_id: str,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> TablesOut:
    """Every table the source exposes, and the structure of the ones the agent may use.

    Synchronous: a connection registered before tables were tracked is listed on its first read
    here, against the customer's database, which belongs in the threadpool.
    """
    conn = svc.get_connection(db, ctx.tenant_id, connection_id)
    tables_svc.ensure_listed(db, conn)
    return TablesOut.model_validate(tables_svc.view(db, conn))


@router.put("/{connection_id}/tables", response_model=TablesOut)
def choose_tables(
    connection_id: str,
    body: TableSelection,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> TablesOut:
    """Replace the selection. The chosen tables' structure is read before this returns."""
    conn = svc.get_connection(db, ctx.tenant_id, connection_id)
    return TablesOut.model_validate(tables_svc.save_selection(db, conn, body.tables))


@router.post("/{connection_id}/tables/refresh", response_model=TablesRefreshOut)
def refresh_tables(
    connection_id: str,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> TablesRefreshOut:
    conn = svc.get_connection(db, ctx.tenant_id, connection_id)
    return TablesRefreshOut.model_validate(tables_svc.refresh(db, conn))


@router.delete("/{connection_id}", status_code=204, response_class=Response)
def delete(
    connection_id: str,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> Response:
    """Retire a connection and destroy its stored credential.

    404 for unknown, another tenant's, and already-deleted alike, so a second delete is a 404
    rather than a 204. Consistent with every other lookup here, which is worth more than
    idempotence.
    """
    svc.delete_connection(db, ctx.tenant_id, connection_id)
    return Response(status_code=204)

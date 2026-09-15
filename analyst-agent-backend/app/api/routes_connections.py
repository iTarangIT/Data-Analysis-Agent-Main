import os
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import current_tenant
from app.api.schemas import (
    UPLOAD_SUFFIXES,
    ConnectionCreate,
    ConnectionOut,
    TableSelection,
    TablesOut,
    TablesRefreshOut,
)
from app.config import get_settings
from app.db.models import Connection
from app.db.session import get_db
from app.security.auth import TenantContext
from app.services import connections as svc
from app.services import tables as tables_svc

router = APIRouter()


def _out(c: Connection, counts: dict[str, tuple[int, int]]) -> ConnectionOut:
    selected, total = counts.get(c.id, (0, 0))
    return ConnectionOut(
        id=c.id,
        name=c.name,
        kind=c.kind,
        selected_tables=selected,
        total_tables=total,
        catalog_refreshed_at=c.catalog_refreshed_at,
    )


@router.post("", response_model=ConnectionOut, status_code=201)
def create(
    body: ConnectionCreate,
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    conn = svc.create_connection(db, ctx.tenant_id, body.name, body.kind, body.secret)
    return _out(conn, tables_svc.counts(db, [conn.id]))


@router.get("", response_model=list[ConnectionOut])
def list_(
    ctx: TenantContext = Depends(current_tenant), db: Session = Depends(get_db)
) -> list[ConnectionOut]:
    connections = svc.list_connections(db, ctx.tenant_id)
    counts = tables_svc.counts(db, [c.id for c in connections])
    return [_out(c, counts) for c in connections]


@router.post("/file", response_model=ConnectionOut, status_code=201)
def create_from_file(
    file: UploadFile,
    name: Annotated[str, Form(min_length=1, max_length=200)],
    ctx: TenantContext = Depends(current_tenant),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    """Upload a spreadsheet and register it as a connection.

    A separate path because `POST /connections` already carries a JSON body and one route
    cannot take both. Doing the upload and the registration together also avoids an orphaned
    file when only one of the two succeeds.

    Synchronous, so FastAPI runs the whole thing, staging and ingest included, in its
    threadpool rather than on the event loop.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in UPLOAD_SUFFIXES:
        raise HTTPException(415, f"upload one of {sorted(UPLOAD_SUFFIXES)}")

    limit = get_settings().max_upload_bytes
    fd, staged_name = tempfile.mkstemp(suffix=suffix)
    staged = Path(staged_name)
    try:
        written = 0
        # Closed before the finally unlinks it: Windows refuses to delete an open file.
        with os.fdopen(fd, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    # content-length is client-controlled, so the running total is the guard.
                    raise HTTPException(413, f"uploads are limited to {limit} bytes")
                out.write(chunk)

        conn = svc.create_file_connection(db, ctx.tenant_id, name, staged, file.filename or "")
    finally:
        staged.unlink(missing_ok=True)
    return _out(conn, tables_svc.counts(db, [conn.id]))


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

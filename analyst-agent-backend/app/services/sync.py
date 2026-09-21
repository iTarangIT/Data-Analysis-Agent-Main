import json
import os
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks
from googleapiclient.errors import HttpError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import queue
from app.config import get_settings
from app.connectors import storage
from app.connectors.duckdb import FileSource, _slug, _unique, ingest_upload
from app.connectors.gdrive import FOLDER, SHORTCUT, SUFFIXES, Drive, kind_of, reason
from app.connectors.sandbox import Sandbox
from app.db.models import Connection, DatasetFile, DatasetSource
from app.db.session import SessionLocal, _engine
from app.logging import log
from app.services import tables
from app.services.connections import store_part
from app.services.errors import DomainError


def root_of(source: DatasetSource) -> str:
    if source.remote_id is None:
        raise DomainError("uploaded files are managed by uploading them")
    return source.remote_id


def _take(item: dict[str, Any], found: dict[str, Any], skipped: list[dict[str, str]]) -> None:
    if item["mimeType"] == SHORTCUT:
        skipped.append({"name": item["name"], "reason": "a shortcut - add the original instead"})
    elif kind_of(item) in ("other", "folder"):
        skipped.append({"name": item["name"], "reason": "not a supported file type"})
    elif not item.get("capabilities", {}).get("canDownload", True):
        skipped.append({"name": item["name"], "reason": "its owner has turned off downloading"})
    else:
        found[item["id"]] = item


def walk(
    drive: Drive, source: DatasetSource, rules: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    settings = get_settings()
    found: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, str]] = []
    root = root_of(source)
    if source.origin in ("gdrive_file", "gsheet"):
        _take(drive.get(root), found, skipped)
        return list(found.values()), skipped

    frontier = {rule["id"]: (0, rule["recursive"]) for rule in rules if rule["kind"] == "folder"}
    while frontier:
        following: dict[str, tuple[int, bool]] = {}
        for item in drive.children(list(frontier)):
            depth, recursive = next(
                (frontier[parent] for parent in item.get("parents", []) if parent in frontier),
                (0, False),
            )
            if item["mimeType"] != FOLDER:
                _take(item, found, skipped)
            elif recursive and depth < settings.drive_max_depth:
                following[item["id"]] = (depth + 1, True)
            elif recursive:
                reason = f"deeper than {settings.drive_max_depth} folders"
                skipped.append({"name": f"{item['name']}/", "reason": reason})
        frontier = following

    wanted = [rule["id"] for rule in rules if rule["kind"] == "file" and rule["id"] not in found]
    allowed = {root, *(source.seen_folders or [])}
    fetched = drive.get_many(wanted) if wanted else {}
    for file_id in wanted:
        if file_id not in fetched:
            skipped.append({"name": file_id, "reason": "no longer there"})
        elif allowed.isdisjoint(fetched[file_id].get("parents", [])):
            skipped.append({"name": fetched[file_id]["name"], "reason": "not in this source"})
        else:
            _take(fetched[file_id], found, skipped)

    ordered = sorted(found.values(), key=lambda item: item["name"].lower())
    limit = settings.drive_max_files
    skipped += [
        {"name": item["name"], "reason": f"past the {limit}-file limit"} for item in ordered[limit:]
    ]
    return ordered[:limit], skipped


async def request(connection_id: str, tasks: BackgroundTasks) -> None:
    if get_settings().queue_enabled:
        await queue.pool().enqueue_job(
            "sync_dataset", connection_id, _job_id=f"sync:{connection_id}"
        )
    else:
        tasks.add_task(sync_dataset, connection_id)


async def refresh_if_stale(db: Session, connection_id: str, tasks: BackgroundTasks) -> None:
    conn = db.get_one(Connection, connection_id)
    after = timedelta(minutes=get_settings().google_sync_after_minutes)
    if (
        conn.kind != "file"
        or conn.sync_status == "syncing"
        or (conn.synced_at is not None and datetime.now(UTC) - conn.synced_at < after)
    ):
        return
    google = select(DatasetSource.id).where(
        DatasetSource.connection_id == conn.id,
        DatasetSource.origin != "upload",
        DatasetSource.status == "active",
    )
    if db.scalar(google.limit(1)) is not None:
        await request(conn.id, tasks)


def sync_dataset(connection_id: str) -> None:
    lock = func.hashtext(f"sync:{connection_id}")
    with _engine.connect() as held:
        if not held.execute(select(func.pg_try_advisory_lock(lock))).scalar():
            log.info("sync.already_running", connection_id=connection_id)
            return
        held.commit()
        try:
            _run(connection_id)
        finally:
            held.execute(select(func.pg_advisory_unlock(lock)))
            held.commit()


def _run(connection_id: str) -> None:
    db = SessionLocal()
    try:
        conn = db.get(Connection, connection_id)
        if conn is None or conn.deleted_at is not None:
            return
        conn.sync_status = "syncing"
        db.commit()
        try:
            _sync(db, conn)
        except Exception:
            db.rollback()
            log.exception("sync.failed", connection_id=connection_id)
            conn.sync_status = "failed"
        else:
            conn.sync_status, conn.synced_at = "ready", datetime.now(UTC)
        db.commit()
    finally:
        db.close()


def _sync(db: Session, conn: Connection) -> None:
    sources = db.scalars(
        select(DatasetSource)
        .where(
            DatasetSource.connection_id == conn.id,
            DatasetSource.origin != "upload",
            DatasetSource.status == "active",
        )
        .order_by(DatasetSource.created_at)
    ).all()
    keys = {s.remote_id: s.resource_key for s in sources if s.remote_id and s.resource_key}
    drive = Drive(conn.tenant_id, keys)
    with Sandbox() as sandbox, tempfile.TemporaryDirectory() as staging:
        for source in sources:
            _sync_source(db, conn, source, drive, sandbox, Path(staging))
            db.expire(conn, ["files"])
    _describe(db, conn, sources)
    tables.refresh(db, conn)


def _sync_source(
    db: Session,
    conn: Connection,
    source: DatasetSource,
    drive: Drive,
    sandbox: Sandbox,
    staging: Path,
) -> None:
    settings = get_settings()
    found, _ = walk(drive, source, source.rules or [])
    drive.keys |= {item["id"]: item["resourceKey"] for item in found if item.get("resourceKey")}
    held = {f.remote_id: f for f in conn.files if f.source_id == source.id}
    present = {item["id"] for item in found}
    gone = [f for f in held.values() if f.remote_id not in present]
    for f in gone:
        db.delete(f)
    db.commit()
    storage.delete([part for f in gone for part in f.parts])

    titles = _tabs(drive, source) if source.origin == "gsheet" else None
    parsed: list[tuple[DatasetFile, list[FileSource]]] = []
    for item in found:
        version = item.get("md5Checksum") or item["modifiedTime"]
        row = held.get(item["id"])
        if row is not None and row.remote_version == version and row.status != "failed":
            continue
        if row is None:
            row = DatasetFile(
                id=str(uuid.uuid4()),
                source_id=source.id,
                connection_id=conn.id,
                remote_id=item["id"],
                parts=[],
            )
        row.name, row.mime, row.remote_version = item["name"], item["mimeType"], version
        row.bytes, row.synced_at = int(item.get("size") or 0), datetime.now(UTC)
        if kind_of(item) != "sheet" and row.bytes > settings.max_upload_bytes:
            limit = settings.max_upload_bytes // 2**20
            _settle(db, row, "skipped", f"over the {limit} MB limit for one file")
            continue
        try:
            path = _fetch(drive, item, staging, titles)
            parts = sandbox.run(
                item["name"],
                ingest_upload,
                path,
                staging / row.id,
                item["name"],
                set(),
                source_column=source.combine,
                sheets=titles,
            )
        except DomainError as e:
            _settle(db, row, "failed", str(e))
            continue
        except HttpError as e:
            log.warning("sync.download_failed", file=item["id"], reason=reason(e))
            _settle(db, row, "failed", "Google Drive would not hand it over")
            continue
        parsed.append((row, parts))
    _place(db, conn, source, parsed)


def _tabs(drive: Drive, source: DatasetSource) -> list[str]:
    wanted = {rule["id"] for rule in source.rules or []}
    tabs = drive.sheet_tabs(root_of(source))
    return [tab["title"] for tab in tabs if str(tab["sheetId"]) in wanted]


def _fetch(drive: Drive, item: dict[str, Any], staging: Path, titles: list[str] | None) -> Path:
    kind = kind_of(item)
    dest = staging / f"{item['id']}{SUFFIXES[kind]}"
    if kind != "sheet":
        drive.download(item["id"], dest)
        return dest
    try:
        drive.export_xlsx(item["id"], dest)
        return dest
    except HttpError as e:
        if reason(e) != "exportSizeLimitExceeded":
            raise
    if titles is None:
        tabs = drive.sheet_tabs(item["id"])
        titles = [tab["title"] for tab in tabs if tab.get("sheetType", "GRID") == "GRID"]
    values = drive.sheet_values(item["id"], titles)
    dest = staging / f"{item['id']}.json"
    dest.write_text(json.dumps(values, default=str), encoding="utf-8")
    return dest


def _settle(db: Session, row: DatasetFile, status: str, why: str) -> None:
    stale = row.parts
    row.status, row.reason, row.parts = status, why, []
    db.add(row)
    db.commit()
    storage.delete(stale)


def _stem(row: DatasetFile) -> str:
    if kind_of({"mimeType": row.mime}) == "sheet" or "." not in row.name:
        return row.name
    return row.name.rsplit(".", 1)[0]


def _common(stems: list[str]) -> str:
    prefix = os.path.commonprefix(stems)
    if len(set(stems)) > 1:
        cut = max(prefix.rfind(mark) for mark in " _-.")
        prefix = prefix[:cut] if cut > 0 else ""
    return prefix.strip(" _-.")


def _place(
    db: Session,
    conn: Connection,
    source: DatasetSource,
    parsed: list[tuple[DatasetFile, list[FileSource]]],
) -> None:
    settings = get_settings()
    replaced = {row.id for row, _ in parsed}
    ready = [f for f in conn.files if f.status == "ready" and f.id not in replaced]
    taken = {part["table"] for f in conn.files for part in f.parts}
    matched: dict[frozenset[str], str] = {}
    if source.combine:
        matched = {
            frozenset(part["profile"]["columns"]): part["table"]
            for f in ready
            if f.source_id == source.id
            for part in f.parts
        }
        pending: dict[frozenset[str], list[str]] = {}
        for row, parts in parsed:
            earlier = {part["sheet"] for part in row.parts}
            for part in parts:
                columns = frozenset(part.profile["columns"])
                if part.sheet not in earlier and columns not in matched:
                    pending.setdefault(columns, []).append(_stem(row))
        for columns, stems in pending.items():
            matched[columns] = _unique(_slug(_common(stems) or source.label), taken)
            taken.add(matched[columns])

    budget = settings.max_dataset_bytes - sum(part["bytes"] for f in ready for part in f.parts)
    for row, parts in parsed:
        size = sum(Path(part.path).stat().st_size for part in parts)
        if size > budget:
            _settle(db, row, "skipped", "it would take the dataset past its size limit")
            continue
        budget -= size
        previous = {part["sheet"]: part["table"] for part in row.parts}
        placed = []
        for part in parts:
            table = previous.get(part.sheet) or matched.get(frozenset(part.profile["columns"]))
            if table is None:
                table = _unique(part.table, taken)
                taken.add(table)
            placed.append(replace(part, table=table))
        stored = [store_part(conn.tenant_id, conn.id, row.id, part) for part in placed]
        kept = {part["storage_key"] for part in stored}
        stale = [part for part in row.parts if part["storage_key"] not in kept]
        row.parts, row.status, row.reason = stored, "ready", None
        db.add(row)
        db.commit()
        storage.delete(stale)


def _describe(db: Session, conn: Connection, sources: Sequence[DatasetSource]) -> None:
    labels = {source.id: source.label for source in sources}
    ready = [f for f in conn.files if f.status == "ready" and f.source_id in labels]
    feeding: dict[str, set[str]] = {}
    for f in ready:
        for part in f.parts:
            feeding.setdefault(part["table"], set()).add(f.id)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    for f in ready:
        f.parts = [
            {
                **part,
                "profile": {
                    **part["profile"],
                    "comment": _comment(labels[f.source_id], len(feeding[part["table"]]), stamp),
                },
            }
            for part in f.parts
        ]
    db.commit()


def _comment(label: str, files: int, stamp: str) -> str:
    return f"Google Drive: {label}, {files} file{'' if files == 1 else 's'}, synced {stamp}"

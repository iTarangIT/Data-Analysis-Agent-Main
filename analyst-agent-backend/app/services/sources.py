from typing import Any

from googleapiclient.errors import HttpError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors import storage
from app.connectors.gdrive import SHORTCUT, Drive, kind_of, parse_link, reason
from app.db.models import Connection, DatasetFile, DatasetSource, User
from app.logging import log
from app.services import sync, tables
from app.services.errors import DomainError, Forbidden, NotFound, SourceUnavailable

NEEDS_SHARE = {
    "notFound",
    "insufficientFilePermissions",
    "appNotAuthorizedToFile",
    "teamDriveMembershipRequired",
    "domainPolicy",
}
ORIGINS = {"folder": "gdrive_folder", "sheet": "gsheet"}


def unreachable(e: HttpError) -> SourceUnavailable:
    log.warning("google.failed", status=e.status_code, reason=reason(e))
    return SourceUnavailable("Google Drive could not be reached just now - try again")


def dataset(conn: Connection) -> Connection:
    if conn.kind != "file":
        raise DomainError("only a dataset takes files from Google Drive")
    return conn


def source_of(db: Session, conn: Connection, source_id: str) -> DatasetSource:
    source = db.get(DatasetSource, source_id)
    if source is None or source.connection_id != dataset(conn).id:
        raise NotFound("this dataset has no such source")
    return source


def view(source: DatasetSource, files: list[DatasetFile]) -> dict[str, Any]:
    return {
        "id": source.id,
        "origin": source.origin,
        "label": source.label,
        "status": source.status,
        "combine": source.combine,
        "rules": source.rules or [],
        "files": [
            {
                "id": f.id,
                "name": f.name,
                "status": f.status,
                "reason": f.reason,
                "bytes": f.bytes,
                "synced_at": f.synced_at,
                "tables": sorted({part["table"] for part in f.parts}),
            }
            for f in files
        ],
    }


def drive_for(conn: Connection, source: DatasetSource) -> Drive:
    if source.remote_id and source.resource_key:
        return Drive(conn.tenant_id, {source.remote_id: source.resource_key})
    return Drive(conn.tenant_id)


def _node(item: dict[str, Any]) -> dict[str, Any]:
    kind = kind_of(item)
    return {
        "id": item["id"],
        "name": item["name"],
        "kind": kind,
        "supported": kind != "other",
        "bytes": int(item["size"]) if "size" in item else None,
        "modified": item.get("modifiedTime"),
    }


def _listing(folder_id: str, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    nodes.sort(key=lambda node: (node["kind"] != "folder", node["name"].lower()))
    return {
        "folder_id": folder_id,
        "children": nodes,
        "supported": sum(node["supported"] for node in nodes),
        "unsupported": sum(not node["supported"] for node in nodes),
        "bytes": sum(node["bytes"] or 0 for node in nodes if node["kind"] != "folder"),
    }


def tree(db: Session, conn: Connection, source_id: str, folder_id: str | None) -> dict[str, Any]:
    source = source_of(db, conn, source_id)
    root = sync.root_of(source)
    drive = drive_for(conn, source)
    if source.origin == "gsheet":
        try:
            tabs = drive.sheet_tabs(root)
        except HttpError as e:
            raise unreachable(e) from e
        nodes = [
            {
                "id": str(tab["sheetId"]),
                "name": tab["title"],
                "kind": "sheet",
                "supported": tab.get("sheetType", "GRID") == "GRID",
                "bytes": None,
                "modified": None,
            }
            for tab in tabs
        ]
        return _listing(root, nodes)
    if source.origin != "gdrive_folder":
        raise DomainError("only a folder or a sheet can be browsed")

    folder = folder_id or root
    db.refresh(source, with_for_update=True)
    seen = list(source.seen_folders or [])
    if folder != root and folder not in seen:
        raise NotFound("that folder is not part of this source")
    try:
        nodes = [_node(item) for item in drive.children([folder])]
    except HttpError as e:
        raise unreachable(e) from e
    source.seen_folders = seen + [
        node["id"] for node in nodes if node["kind"] == "folder" and node["id"] not in seen
    ]
    db.commit()
    return _listing(folder, nodes)


def _check(source: DatasetSource, rules: list[dict[str, Any]], dry_run: bool) -> None:
    if source.origin == "upload":
        raise DomainError("uploaded files are chosen by uploading them")
    if not rules and not dry_run:
        raise DomainError("choose at least one folder, file or tab")
    kinds = {"gdrive_folder": {"folder", "file"}, "gsheet": {"sheet"}, "gdrive_file": {"file"}}
    if any(rule["kind"] not in kinds[source.origin] for rule in rules) or (
        source.origin == "gdrive_file" and any(r["id"] != source.remote_id for r in rules)
    ):
        raise DomainError("those choices do not fit this source")
    known = {source.remote_id, *(source.seen_folders or [])}
    if any(rule["kind"] == "folder" and rule["id"] not in known for rule in rules):
        raise NotFound("that folder is not part of this source")


def choose(
    db: Session,
    conn: Connection,
    source_id: str,
    rules: list[dict[str, Any]],
    combine: bool,
    dry_run: bool,
) -> dict[str, Any]:
    source = source_of(db, conn, source_id)
    _check(source, rules, dry_run)
    if not dry_run:
        source.rules, source.combine, source.status = rules, combine, "active"
        db.commit()
        return view(source, [f for f in conn.files if f.source_id == source.id])

    try:
        found, skipped = sync.walk(drive_for(conn, source), source, rules)
    except HttpError as e:
        raise unreachable(e) from e
    size = sum(int(item.get("size") or 0) for item in found)
    held = sum(part["bytes"] for f in conn.files if f.source_id != source.id for part in f.parts)
    limit = get_settings().max_dataset_bytes
    return {
        "files": len(found),
        "bytes": size,
        "skipped": skipped,
        "fits": held + size <= limit,
        "limit": limit,
    }


def overview(db: Session, conn: Connection) -> dict[str, Any]:
    sources = db.scalars(
        select(DatasetSource)
        .where(DatasetSource.connection_id == dataset(conn).id)
        .order_by(DatasetSource.created_at)
    ).all()
    files: dict[str, list[DatasetFile]] = {}
    for f in conn.files:
        files.setdefault(f.source_id, []).append(f)
    return {
        "sync_status": conn.sync_status,
        "synced_at": conn.synced_at,
        "sources": [view(source, files.get(source.id, [])) for source in sources],
    }


def remove(db: Session, conn: Connection, source_id: str) -> dict[str, Any]:
    source = source_of(db, conn, source_id)
    if source.origin == "upload":
        raise DomainError("uploaded files are removed one at a time")
    files = [f for f in conn.files if f.source_id == source.id]
    for f in files:
        db.delete(f)
    db.flush()
    db.delete(source)
    db.commit()
    storage.delete([part for f in files for part in f.parts])
    db.expire(conn, ["files"])
    tables.refresh(db, conn)
    return overview(db, conn)


def _shared_by_member(db: Session, tenant_id: str, email: str | None) -> bool:
    if email is None:
        return False
    member = select(User.id).where(
        User.tenant_id == tenant_id,
        User.is_active,
        func.lower(User.email) == email.lower(),
    )
    return db.scalar(member.limit(1)) is not None


def _first_rules(drive: Drive, origin: str, remote_id: str, gid: int | None) -> list[dict]:
    if origin == "gdrive_file":
        return [{"id": remote_id, "kind": "file", "recursive": False}]
    if origin == "gdrive_folder":
        return []
    tabs = [tab for tab in drive.sheet_tabs(remote_id) if tab.get("sheetType", "GRID") == "GRID"]
    chosen = [tab for tab in tabs if tab["sheetId"] == gid] or tabs
    return [{"id": str(tab["sheetId"]), "kind": "sheet", "recursive": False} for tab in chosen]


def resolve(db: Session, conn: Connection, user_id: str, url: str, confirm: bool) -> dict[str, Any]:
    dataset(conn)
    link = parse_link(url)
    drive = Drive(conn.tenant_id, {link.id: link.resource_key} if link.resource_key else {})
    try:
        item = drive.get(link.id)
        if item["mimeType"] == SHORTCUT:
            target = item["shortcutDetails"]
            if target.get("targetResourceKey"):
                drive.keys[target["targetId"]] = target["targetResourceKey"]
            item = drive.get(target["targetId"])
    except HttpError as e:
        if e.status_code == 404 or reason(e) in NEEDS_SHARE:
            return {"status": "needs_share", "share_with": drive.email}
        raise unreachable(e) from e

    if item.get("trashed"):
        raise DomainError("that item is in its owner's trash")
    kind = kind_of(item)
    if kind == "other":
        raise DomainError("share a folder, a Google Sheet, or an xlsx, csv, tsv or pdf file")

    sharer = (item.get("sharingUser") or {}).get("emailAddress")
    if not _shared_by_member(db, conn.tenant_id, sharer):
        if not confirm:
            return {"status": "unverified"}
        if db.get_one(User, user_id).role != "owner":
            raise Forbidden("only an owner of your organisation can add what nobody in it shared")
        log.warning(
            "google.unverified_share_confirmed",
            tenant_id=conn.tenant_id,
            user_id=user_id,
            remote_id=item["id"],
        )

    source = db.scalar(
        select(DatasetSource).where(
            DatasetSource.connection_id == conn.id, DatasetSource.remote_id == item["id"]
        )
    )
    if source is None:
        origin = ORIGINS.get(kind, "gdrive_file")
        try:
            rules = _first_rules(drive, origin, item["id"], link.gid)
        except HttpError as e:
            raise unreachable(e) from e
        source = DatasetSource(
            connection_id=conn.id,
            origin=origin,
            remote_id=item["id"],
            resource_key=item.get("resourceKey") or link.resource_key,
            label=item["name"],
            combine=True,
            rules=rules,
            seen_folders=[],
            status="pending",
        )
        db.add(source)
        db.commit()
    return {"status": "resolved", "source": view(source, [])}

from typing import Any

from googleapiclient.errors import HttpError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.connectors.gdrive import SHORTCUT, Drive, kind_of, parse_link, reason
from app.db.models import Connection, DatasetFile, DatasetSource, User
from app.logging import log
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

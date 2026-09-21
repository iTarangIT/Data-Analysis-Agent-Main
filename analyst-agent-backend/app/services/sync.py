from typing import Any

from app.config import get_settings
from app.connectors.gdrive import FOLDER, SHORTCUT, Drive, kind_of
from app.db.models import DatasetSource
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

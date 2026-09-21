import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from app.config import get_settings
from app.services.errors import DomainError

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]
FOLDER = "application/vnd.google-apps.folder"
SHEET = "application/vnd.google-apps.spreadsheet"
SHORTCUT = "application/vnd.google-apps.shortcut"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
KINDS = {
    FOLDER: "folder",
    SHEET: "sheet",
    XLSX: "xlsx",
    "text/csv": "csv",
    "text/tab-separated-values": "tsv",
    "application/pdf": "pdf",
}
SUFFIXES = {"sheet": ".xlsx", "xlsx": ".xlsx", "csv": ".csv", "tsv": ".tsv", "pdf": ".pdf"}
FIELDS = (
    "id,name,mimeType,size,md5Checksum,modifiedTime,parents,resourceKey,trashed,"
    "capabilities(canDownload),shortcutDetails(targetId,targetMimeType,targetResourceKey)"
)
ID = r"[A-Za-z0-9_-]{10,}"
KEY = r"[A-Za-z0-9_-]+"
SHAPES = [
    ("docs.google.com", re.compile(rf"/spreadsheets/d/({ID})(?:/.*)?")),
    ("drive.google.com", re.compile(rf"/drive/(?:u/\d+/)?folders/({ID})/?")),
    ("drive.google.com", re.compile(rf"/file/d/({ID})(?:/.*)?")),
]
LIST_GROUP = 50
BATCH = 100


@dataclass(frozen=True)
class Link:
    id: str
    resource_key: str | None
    gid: int | None


def parse_link(url: str) -> Link:
    parsed = urlparse(url.strip())
    query = parse_qs(parsed.query)
    found = None
    if parsed.scheme == "https" and parsed.netloc == "drive.google.com" and parsed.path == "/open":
        found = next((value for value in query.get("id", []) if re.fullmatch(ID, value)), None)
    elif parsed.scheme == "https":
        for host, shape in SHAPES:
            if parsed.netloc == host and (match := shape.fullmatch(parsed.path)):
                found = match.group(1)
    key = next(iter(query.get("resourcekey", [])), None)
    gid = next(iter(query.get("gid") or parse_qs(parsed.fragment).get("gid", [])), None)
    if found is None or (key is not None and not re.fullmatch(KEY, key)):
        raise DomainError("paste a Google Drive or Google Sheets link")
    return Link(id=found, resource_key=key, gid=int(gid) if gid and gid.isdigit() else None)


def reason(error: HttpError) -> str:
    try:
        return str(json.loads(error.content)["error"]["errors"][0]["reason"])
    except (ValueError, KeyError, IndexError, TypeError):
        return ""


def kind_of(item: dict[str, Any]) -> str:
    return KINDS.get(item["mimeType"], "other")


def _a1(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


class Drive:
    def __init__(self, tenant_id: str, keys: dict[str, str] | None = None) -> None:
        secret = get_settings().google_service_account_json
        if secret is None:
            raise DomainError("Google sources aren't configured")
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(secret.get_secret_value()), scopes=SCOPES
        )
        self.email: str = credentials.service_account_email
        self.tenant_id = tenant_id
        self.keys = dict(keys or {})
        self._drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self._sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    def _keyed(self, request: Any, *ids: str) -> Any:
        keys = [f"{i}/{self.keys[i]}" for i in ids if i in self.keys]
        if keys:
            request.headers["X-Goog-Drive-Resource-Keys"] = ",".join(keys)
        return request

    def get(self, file_id: str) -> dict[str, Any]:
        request = self._drive.files().get(
            fileId=file_id,
            fields=f"{FIELDS},sharingUser(emailAddress)",
            supportsAllDrives=True,
            quotaUser=self.tenant_id,
        )
        return self._keyed(request, file_id).execute(num_retries=3)

    def get_many(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}

        def keep(request_id: str, response: dict[str, Any], exception: Exception | None) -> None:
            if exception is None:
                found[request_id] = response

        for start in range(0, len(ids), BATCH):
            batch = self._drive.new_batch_http_request(callback=keep)
            for file_id in ids[start : start + BATCH]:
                request = self._drive.files().get(
                    fileId=file_id, fields=FIELDS, supportsAllDrives=True, quotaUser=self.tenant_id
                )
                batch.add(self._keyed(request, file_id), request_id=file_id)
            batch.execute()
        return found

    def children(self, folder_ids: list[str]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for start in range(0, len(folder_ids), LIST_GROUP):
            group = folder_ids[start : start + LIST_GROUP]
            listed = self._list(group)
            if len(group) > 1:
                answered = {parent for item in listed for parent in item.get("parents", [])}
                for folder in group:
                    if folder not in answered:
                        listed += self._list([folder])
            found += listed
        return found

    def _list(self, folder_ids: list[str]) -> list[dict[str, Any]]:
        parents = " or ".join(f"'{folder}' in parents" for folder in folder_ids)
        items: list[dict[str, Any]] = []
        token = None
        while True:
            request = self._drive.files().list(
                q=f"trashed = false and ({parents})",
                fields=f"nextPageToken,files({FIELDS})",
                pageSize=1000,
                pageToken=token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                quotaUser=self.tenant_id,
            )
            page = self._keyed(request, *folder_ids).execute(num_retries=3)
            items += page.get("files", [])
            token = page.get("nextPageToken")
            if token is None:
                return items

    def download(self, file_id: str, dest: Path) -> None:
        request = self._drive.files().get_media(
            fileId=file_id, supportsAllDrives=True, quotaUser=self.tenant_id
        )
        self._save(self._keyed(request, file_id), dest)

    def export_xlsx(self, file_id: str, dest: Path) -> None:
        request = self._drive.files().export_media(
            fileId=file_id, mimeType=XLSX, quotaUser=self.tenant_id
        )
        self._save(self._keyed(request, file_id), dest)

    def _save(self, request: Any, dest: Path) -> None:
        with dest.open("wb") as out:
            downloader = MediaIoBaseDownload(out, request)
            done = False
            while not done:
                _, done = downloader.next_chunk(num_retries=3)

    def sheet_tabs(self, spreadsheet_id: str) -> list[dict[str, Any]]:
        found = (
            self._sheets.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="sheets.properties(sheetId,title,sheetType)",
                quotaUser=self.tenant_id,
            )
            .execute(num_retries=3)
        )
        return [sheet["properties"] for sheet in found.get("sheets", [])]

    def sheet_values(self, spreadsheet_id: str, titles: list[str]) -> dict[str, list[list[Any]]]:
        found = (
            self._sheets.spreadsheets()
            .values()
            .batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=[_a1(title) for title in titles],
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="FORMATTED_STRING",
                quotaUser=self.tenant_id,
            )
            .execute(num_retries=3)
        )
        return {
            title: block.get("values", [])
            for title, block in zip(titles, found.get("valueRanges", []), strict=True)
        }

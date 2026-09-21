import json
from urllib.parse import parse_qs, urlparse

import httplib2
import pytest
from googleapiclient.errors import HttpError

from app.connectors import gdrive
from app.connectors.gdrive import XLSX, Drive, parse_link, reason
from app.services.errors import DomainError

FOLDER_ID = "1AbCdEfGhIjKlMnOpQrStUv"
FILE_ID = "1ZyXwVuTsRqPoNmLkJiHgFe"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"https://docs.google.com/spreadsheets/d/{FILE_ID}/edit#gid=42", (FILE_ID, None, 42)),
        (f"https://docs.google.com/spreadsheets/d/{FILE_ID}/edit?gid=7#gid=7", (FILE_ID, None, 7)),
        (f"https://docs.google.com/spreadsheets/d/{FILE_ID}", (FILE_ID, None, None)),
        (f"https://drive.google.com/drive/folders/{FOLDER_ID}", (FOLDER_ID, None, None)),
        (f"https://drive.google.com/drive/u/1/folders/{FOLDER_ID}", (FOLDER_ID, None, None)),
        (
            f"https://drive.google.com/drive/folders/{FOLDER_ID}?resourcekey=0-abc_DEF",
            (FOLDER_ID, "0-abc_DEF", None),
        ),
        (f"https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing", (FILE_ID, None, None)),
        (f"https://drive.google.com/open?id={FILE_ID}", (FILE_ID, None, None)),
        (f"  https://drive.google.com/file/d/{FILE_ID}  ", (FILE_ID, None, None)),
    ],
)
def test_a_link_of_an_accepted_shape_is_read(url, expected):
    link = parse_link(url)

    assert (link.id, link.resource_key, link.gid) == expected


@pytest.mark.parametrize(
    "url",
    [
        f"http://drive.google.com/drive/folders/{FOLDER_ID}",
        f"https://drive.google.com.evil.example/drive/folders/{FOLDER_ID}",
        f"https://evil.example/drive/folders/{FOLDER_ID}",
        f"https://docs.google.com/document/d/{FILE_ID}/edit",
        f"https://drive.google.com/drive/folders/{FOLDER_ID}/../x",
        "https://drive.google.com/drive/folders/short",
        "https://drive.google.com/open?id=../../etc",
        f"https://drive.google.com/drive/folders/{FOLDER_ID}?resourcekey=0%0AInjected:1",
        "not a link",
        "",
    ],
)
def test_anything_else_is_refused(url):
    with pytest.raises(DomainError, match="paste a Google Drive or Google Sheets link"):
        parse_link(url)


def test_without_credentials_every_google_call_is_refused(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "google_service_account_json", None, raising=False)

    with pytest.raises(DomainError, match="Google sources aren't configured"):
        Drive("t_a")


def test_a_drive_error_is_read_for_its_reason():
    errors = [{"reason": "exportSizeLimitExceeded"}]
    content = json.dumps({"error": {"code": 403, "message": "too large", "errors": errors}})
    refused = HttpError(httplib2.Response({"status": 403}), content.encode())

    assert reason(refused) == "exportSizeLimitExceeded"
    assert reason(HttpError(httplib2.Response({"status": 500}), b"<html>")) == ""


class Recorder:
    def __init__(self, *responses: bytes) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str, dict]] = []

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        self.requests.append((method, uri, dict(headers or {})))
        return httplib2.Response({"status": 200}), self.responses.pop(0)

    def query(self, index: int) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.requests[index][1]).query)


@pytest.fixture
def recorder(google_credentials, monkeypatch):
    real_build = gdrive.build
    http = Recorder()

    def offline(name, version, credentials, cache_discovery):
        assert credentials.service_account_email == google_credentials["client_email"]
        return real_build(name, version, http=http, static_discovery=True)

    monkeypatch.setattr(gdrive, "build", offline)
    return http


def test_a_listing_asks_every_drive_and_charges_the_tenant(recorder):
    recorder.responses = [json.dumps({"files": [{"id": "x", "parents": [FOLDER_ID]}]}).encode()]

    Drive("t_a").children([FOLDER_ID])

    query = recorder.query(0)
    assert query["q"] == [f"trashed = false and ('{FOLDER_ID}' in parents)"]
    assert query["supportsAllDrives"] == ["true"]
    assert query["includeItemsFromAllDrives"] == ["true"]
    assert query["quotaUser"] == ["t_a"]
    assert query["pageSize"] == ["1000"]
    assert query["fields"][0].startswith("nextPageToken,files(id,name,mimeType")


def test_folders_share_one_listing_and_an_empty_one_is_asked_again(recorder):
    other = "1OtherFolderIdentifier"
    recorder.responses = [
        json.dumps({"files": [{"id": "x", "parents": [FOLDER_ID]}]}).encode(),
        json.dumps({"files": [{"id": "y", "parents": [other]}]}).encode(),
    ]

    found = Drive("t_a").children([FOLDER_ID, other])

    assert [item["id"] for item in found] == ["x", "y"]
    assert recorder.query(0)["q"] == [
        f"trashed = false and ('{FOLDER_ID}' in parents or '{other}' in parents)"
    ]
    assert recorder.query(1)["q"] == [f"trashed = false and ('{other}' in parents)"]


def test_a_listing_follows_every_page(recorder):
    recorder.responses = [
        json.dumps({"files": [{"id": "x"}], "nextPageToken": "p2"}).encode(),
        json.dumps({"files": [{"id": "y"}]}).encode(),
    ]

    found = Drive("t_a").children([FOLDER_ID])

    assert [item["id"] for item in found] == ["x", "y"]
    assert recorder.query(1)["pageToken"] == ["p2"]


def test_an_export_carries_only_what_export_accepts(recorder, tmp_path):
    recorder.responses = [b"PK xlsx bytes"]

    Drive("t_a").export_xlsx(FILE_ID, tmp_path / "book.xlsx")

    query = recorder.query(0)
    assert query["mimeType"] == [XLSX]
    assert query["quotaUser"] == ["t_a"]
    assert "supportsAllDrives" not in query
    assert (tmp_path / "book.xlsx").read_bytes() == b"PK xlsx bytes"


def test_a_resource_key_travels_as_a_header_for_its_own_file(recorder):
    recorder.responses = [json.dumps({"id": FILE_ID, "name": "Sales"}).encode()]

    Drive("t_a", {FILE_ID: "0-key", FOLDER_ID: "0-other"}).get(FILE_ID)

    _, _, headers = recorder.requests[0]
    assert headers["X-Goog-Drive-Resource-Keys"] == f"{FILE_ID}/0-key"
    assert recorder.query(0)["supportsAllDrives"] == ["true"]
    assert "sharingUser(emailAddress)" in recorder.query(0)["fields"][0]


def test_sheet_values_come_unformatted_with_dates_as_written(recorder):
    recorder.responses = [
        json.dumps({"valueRanges": [{"values": [["a"], [1]]}, {"values": [["b"], [2]]}]}).encode()
    ]

    values = Drive("t_a").sheet_values(FILE_ID, ["July", "Dealer's list"])

    query = recorder.query(0)
    assert values == {"July": [["a"], [1]], "Dealer's list": [["b"], [2]]}
    assert query["ranges"] == ["'July'", "'Dealer''s list'"]
    assert query["valueRenderOption"] == ["UNFORMATTED_VALUE"]
    assert query["dateTimeRenderOption"] == ["FORMATTED_STRING"]

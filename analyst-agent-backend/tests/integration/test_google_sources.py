import pytest
from sqlalchemy import select, text

from app.connectors.gdrive import FOLDER, SHEET

pytestmark = pytest.mark.integration

ROOT = "1RootFolderOfSales2025"
SHEET_ID = "1MonthlyTargetsSheetId"
FOLDER_LINK = f"https://drive.google.com/drive/folders/{ROOT}"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _member_email(db, tenant_id: str = "t_test") -> str:
    from app.db.models import User

    return db.scalar(select(User.email).where(User.tenant_id == tenant_id))


def _resolve(client, token, dataset_id: str, url: str, confirm: bool = False):
    return client.post(
        f"/connections/{dataset_id}/google/resolve",
        headers=_auth(token),
        json={"url": url, "confirm_unverified": confirm},
    )


@pytest.fixture
def dataset_id(client, token, clean_app_db, tmp_path, monkeypatch) -> str:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "file_store_dir", str(tmp_path), raising=False)
    r = client.post("/connections/dataset", headers=_auth(token), json={"name": "Drive sales"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestDataset:
    def test_an_empty_dataset_is_created_to_add_sources_to(self, client, token, dataset_id):
        (listed,) = client.get("/connections", headers=_auth(token)).json()

        assert (listed["id"], listed["kind"], listed["file_count"]) == (dataset_id, "file", 0)
        assert (listed["total_tables"], listed["sync_status"]) == (0, None)


class TestResolving:
    def test_an_item_we_cannot_see_asks_to_be_shared(self, client, token, dataset_id, drive):
        r = _resolve(client, token, dataset_id, FOLDER_LINK)

        assert r.status_code == 200, r.text
        assert r.json() == {"status": "needs_share", "share_with": drive.email, "source": None}

    def test_a_link_of_any_other_shape_never_reaches_google(self, client, token, dataset_id, drive):
        r = _resolve(client, token, dataset_id, "https://evil.example/drive/folders/x")

        assert r.status_code == 400
        assert r.json()["error"] == "paste a Google Drive or Google Sheets link"
        assert drive.calls == []

    def test_a_folder_a_member_shared_becomes_a_pending_source(
        self, client, token, dataset_id, drive, clean_app_db
    ):
        drive.add(ROOT, "Sales 2025", FOLDER, sharer=_member_email(clean_app_db).upper())

        r = _resolve(client, token, dataset_id, FOLDER_LINK)

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "resolved"
        assert {k: body["source"][k] for k in ("origin", "label", "status", "rules")} == {
            "origin": "gdrive_folder",
            "label": "Sales 2025",
            "status": "pending",
            "rules": [],
        }

    def test_resolving_the_same_link_twice_keeps_one_source(
        self, client, token, dataset_id, drive, clean_app_db
    ):
        drive.add(ROOT, "Sales 2025", FOLDER, sharer=_member_email(clean_app_db))

        first = _resolve(client, token, dataset_id, FOLDER_LINK).json()["source"]["id"]
        second = _resolve(client, token, dataset_id, FOLDER_LINK).json()["source"]["id"]

        assert first == second

    def test_a_share_from_outside_the_organisation_waits_for_an_owner(
        self, client, token, dataset_id, drive, clean_app_db
    ):
        drive.add(ROOT, "Sales 2025", FOLDER, sharer="someone@elsewhere.example")

        unconfirmed = _resolve(client, token, dataset_id, FOLDER_LINK).json()
        confirmed = _resolve(client, token, dataset_id, FOLDER_LINK, confirm=True).json()

        assert unconfirmed == {"status": "unverified", "share_with": None, "source": None}
        assert confirmed["status"] == "resolved"

    def test_nobody_but_an_owner_may_confirm_it(
        self, client, token, dataset_id, drive, clean_app_db
    ):
        drive.add(ROOT, "Sales 2025", FOLDER)
        clean_app_db.execute(text("UPDATE users SET role = 'member' WHERE tenant_id = 't_test'"))
        clean_app_db.commit()

        r = _resolve(client, token, dataset_id, FOLDER_LINK, confirm=True)

        assert r.status_code == 403
        assert "owner" in r.json()["error"]

    def test_a_sheet_link_preselects_the_tab_it_names(
        self, client, token, dataset_id, drive, clean_app_db
    ):
        drive.add(SHEET_ID, "Monthly targets", SHEET, sharer=_member_email(clean_app_db))
        drive.tabs[SHEET_ID] = [
            {"sheetId": 0, "title": "January", "sheetType": "GRID"},
            {"sheetId": 42, "title": "February", "sheetType": "GRID"},
            {"sheetId": 7, "title": "Chart", "sheetType": "OBJECT"},
        ]
        link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=42"

        source = _resolve(client, token, dataset_id, link).json()["source"]

        assert (source["origin"], source["rules"]) == (
            "gsheet",
            [{"id": "42", "kind": "sheet", "recursive": False}],
        )

    def test_an_unsupported_file_is_refused(self, client, token, dataset_id, drive, clean_app_db):
        drive.add(ROOT, "slides", "application/vnd.google-apps.presentation")

        r = _resolve(client, token, dataset_id, f"https://drive.google.com/file/d/{ROOT}/view")

        assert r.status_code == 400
        assert "xlsx, csv, tsv or pdf" in r.json()["error"]

    def test_without_credentials_google_is_switched_off(
        self, client, token, dataset_id, monkeypatch
    ):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "google_service_account_json", None, raising=False)

        r = _resolve(client, token, dataset_id, FOLDER_LINK)

        assert r.status_code == 400
        assert r.json()["error"] == "Google sources aren't configured"

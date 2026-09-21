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


CSV_MIME = "text/csv"


@pytest.fixture
def folder_source(client, token, dataset_id, drive, clean_app_db) -> str:
    drive.add(ROOT, "Sales 2025", FOLDER, sharer=_member_email(clean_app_db))
    drive.add("1QuarterOneFolderId", "Q1", FOLDER, parent=ROOT)
    drive.add("1JanuaryCsvFileId000", "Jan.csv", CSV_MIME, parent=ROOT, content=b"a,b\n1,2\n")
    drive.add("1NotesDocumentFileId", "Notes.docx", "application/msword", parent=ROOT, content=b"x")
    drive.add("1DeepFileInQuarterOne", "Feb.csv", CSV_MIME, parent="1QuarterOneFolderId")
    return _resolve(client, token, dataset_id, FOLDER_LINK).json()["source"]["id"]


def _tree(client, token, dataset_id: str, source_id: str, folder_id: str | None = None):
    params = {"source_id": source_id} | ({"folder_id": folder_id} if folder_id else {})
    return client.get(f"/connections/{dataset_id}/google/tree", headers=_auth(token), params=params)


class TestBrowsing:
    def test_the_root_lists_its_own_children_with_counts(
        self, client, token, dataset_id, folder_source
    ):
        r = _tree(client, token, dataset_id, folder_source)

        assert r.status_code == 200, r.text
        body = r.json()
        assert [(n["name"], n["kind"], n["supported"]) for n in body["children"]] == [
            ("Q1", "folder", True),
            ("Jan.csv", "csv", True),
            ("Notes.docx", "other", False),
        ]
        assert (body["supported"], body["unsupported"], body["bytes"]) == (2, 1, 9)

    def test_a_folder_it_has_not_listed_is_refused(
        self, client, token, dataset_id, folder_source, drive
    ):
        drive.add("1SomeoneElsesFolder00", "Payroll", FOLDER)

        r = _tree(client, token, dataset_id, folder_source, "1SomeoneElsesFolder00")

        assert r.status_code == 404
        assert ("children", "1SomeoneElsesFolder00") not in drive.calls

    def test_a_folder_seen_in_a_listing_can_be_opened(
        self, client, token, dataset_id, folder_source
    ):
        _tree(client, token, dataset_id, folder_source)

        r = _tree(client, token, dataset_id, folder_source, "1QuarterOneFolderId")

        assert r.status_code == 200, r.text
        assert [n["name"] for n in r.json()["children"]] == ["Feb.csv"]

    def test_a_sheet_source_lists_its_tabs(self, client, token, dataset_id, drive, clean_app_db):
        drive.add(SHEET_ID, "Monthly targets", SHEET, sharer=_member_email(clean_app_db))
        drive.tabs[SHEET_ID] = [
            {"sheetId": 0, "title": "January", "sheetType": "GRID"},
            {"sheetId": 7, "title": "Chart", "sheetType": "OBJECT"},
        ]
        link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
        source_id = _resolve(client, token, dataset_id, link).json()["source"]["id"]

        r = _tree(client, token, dataset_id, source_id)

        assert [(n["id"], n["kind"], n["supported"]) for n in r.json()["children"]] == [
            ("7", "sheet", False),
            ("0", "sheet", True),
        ]


def _choose(client, token, dataset_id: str, source_id: str, rules: list[dict], **extra):
    return client.post(
        f"/connections/{dataset_id}/sources",
        headers=_auth(token),
        json={"source_id": source_id, "rules": rules} | extra,
    )


def _root_rule(recursive: bool) -> list[dict]:
    return [{"id": ROOT, "kind": "folder", "recursive": recursive}]


class TestChoosing:
    def test_a_dry_run_counts_what_would_come_in_and_writes_nothing(
        self, client, token, dataset_id, folder_source
    ):
        r = _choose(client, token, dataset_id, folder_source, _root_rule(True), dry_run=True)

        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["files"], body["bytes"], body["fits"]) == (2, 8, True)
        assert body["skipped"] == [{"name": "Notes.docx", "reason": "not a supported file type"}]
        sources = client.get(f"/connections/{dataset_id}/sources", headers=_auth(token)).json()
        google = next(s for s in sources["sources"] if s["origin"] == "gdrive_folder")
        assert (google["status"], google["rules"]) == ("pending", [])

    def test_without_subfolders_only_the_folders_own_files_count(
        self, client, token, dataset_id, folder_source
    ):
        r = _choose(client, token, dataset_id, folder_source, _root_rule(False), dry_run=True)

        assert r.json()["files"] == 1

    def test_folders_past_the_depth_limit_are_reported(
        self, client, token, dataset_id, folder_source, monkeypatch
    ):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "drive_max_depth", 0, raising=False)

        body = _choose(
            client, token, dataset_id, folder_source, _root_rule(True), dry_run=True
        ).json()

        assert body["files"] == 1
        assert {"name": "Q1/", "reason": "deeper than 0 folders"} in body["skipped"]

    def test_files_past_the_file_limit_are_reported(
        self, client, token, dataset_id, folder_source, monkeypatch
    ):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "drive_max_files", 1, raising=False)

        body = _choose(
            client, token, dataset_id, folder_source, _root_rule(True), dry_run=True
        ).json()

        assert body["files"] == 1
        assert {"name": "Jan.csv", "reason": "past the 1-file limit"} in body["skipped"]

    def test_a_file_from_outside_the_source_is_left_out(
        self, client, token, dataset_id, folder_source, drive
    ):
        drive.add("1SomeoneElsesFileId00", "payroll.csv", CSV_MIME, parent="1ElsewhereFolder000")
        rules = [{"id": "1SomeoneElsesFileId00", "kind": "file", "recursive": False}]

        body = _choose(client, token, dataset_id, folder_source, rules, dry_run=True).json()

        assert body["files"] == 0
        assert body["skipped"] == [{"name": "payroll.csv", "reason": "not in this source"}]

    def test_a_folder_it_has_never_listed_cannot_be_chosen(
        self, client, token, dataset_id, folder_source
    ):
        rules = [{"id": "1QuarterOneFolderId", "kind": "folder", "recursive": True}]

        r = _choose(client, token, dataset_id, folder_source, rules)

        assert r.status_code == 404

    def test_saving_the_choice_activates_the_source(self, client, token, dataset_id, folder_source):
        r = _choose(client, token, dataset_id, folder_source, _root_rule(True), combine=False)

        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["status"], body["combine"], body["rules"]) == (
            "active",
            False,
            _root_rule(True),
        )

    def test_a_source_can_be_removed_but_the_uploads_cannot(
        self, client, token, dataset_id, folder_source
    ):
        sources = client.get(f"/connections/{dataset_id}/sources", headers=_auth(token)).json()
        upload = next(s["id"] for s in sources["sources"] if s["origin"] == "upload")

        removed = client.delete(
            f"/connections/{dataset_id}/sources/{folder_source}", headers=_auth(token)
        )
        refused = client.delete(f"/connections/{dataset_id}/sources/{upload}", headers=_auth(token))

        assert removed.status_code == 200, removed.text
        assert [s["origin"] for s in removed.json()["sources"]] == ["upload"]
        assert refused.status_code == 400


MONTH = "region,units\nWest,{west}\nEast,{east}\n"


def _month(drive, number: int, version: str = "v1") -> None:
    body = MONTH.format(west=10 * number, east=number).encode()
    drive.add(
        f"1SalesMonthFile00{number:02d}",
        f"Sales 2025-{number:02d}.csv",
        CSV_MIME,
        parent=ROOT,
        content=body,
        version=version,
    )


def _sheet_bytes(rows: list[list]) -> bytes:
    import io

    from openpyxl import Workbook

    book = Workbook()
    for row in rows:
        book.active.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


@pytest.fixture
def sales_folder(client, token, dataset_id, drive, clean_app_db) -> str:
    drive.add(ROOT, "Sales 2025", FOLDER, sharer=_member_email(clean_app_db))
    for number in (1, 2, 3):
        _month(drive, number)
    drive.add(
        "1ReturnsFileId000000",
        "Returns.csv",
        CSV_MIME,
        parent=ROOT,
        content=b"reason,count\nDamaged,3\nLate,1\n",
    )
    return _resolve(client, token, dataset_id, FOLDER_LINK).json()["source"]["id"]


def _tables_of(client, token, dataset_id: str) -> dict[str, dict]:
    r = client.get(f"/connections/{dataset_id}/tables", headers=_auth(token))
    return {t["name"]: t for t in r.json()["tables"]}


def _sources_of(client, token, dataset_id: str) -> dict:
    return client.get(f"/connections/{dataset_id}/sources", headers=_auth(token)).json()


def _google_of(client, token, dataset_id: str) -> dict:
    sources = _sources_of(client, token, dataset_id)["sources"]
    return next(s for s in sources if s["origin"] != "upload")


def _sync(client, token, dataset_id: str):
    return client.post(f"/connections/{dataset_id}/sync", headers=_auth(token))


class TestSyncing:
    def test_saving_a_choice_syncs_the_chosen_files(
        self, client, token, dataset_id, sales_folder, drive
    ):
        r = _choose(client, token, dataset_id, sales_folder, _root_rule(False))

        assert r.status_code == 200, r.text
        assert _sources_of(client, token, dataset_id)["sync_status"] == "ready"
        assert sorted(
            (f["name"], f["status"]) for f in _google_of(client, token, dataset_id)["files"]
        ) == [
            ("Returns.csv", "ready"),
            ("Sales 2025-01.csv", "ready"),
            ("Sales 2025-02.csv", "ready"),
            ("Sales 2025-03.csv", "ready"),
        ]
        assert sorted(drive.downloads()) == sorted(
            ["1ReturnsFileId000000", *(f"1SalesMonthFile00{n:02d}" for n in (1, 2, 3))]
        )

    def test_a_second_sync_of_unchanged_files_downloads_nothing(
        self, client, token, dataset_id, sales_folder, drive
    ):
        _choose(client, token, dataset_id, sales_folder, _root_rule(False))
        drive.calls.clear()

        r = _sync(client, token, dataset_id)

        assert (r.status_code, r.json()) == (202, {"status": "queued"})
        assert drive.downloads() == []
        assert _sources_of(client, token, dataset_id)["sync_status"] == "ready"

    def test_a_changed_file_is_fetched_again_and_a_vanished_one_leaves(
        self, client, token, dataset_id, sales_folder, drive
    ):
        _choose(client, token, dataset_id, sales_folder, _root_rule(False))
        _month(drive, 1, version="v2")
        del drive.items["1SalesMonthFile0002"]
        drive.calls.clear()

        _sync(client, token, dataset_id)

        assert drive.downloads() == ["1SalesMonthFile0001"]
        assert sorted(f["name"] for f in _google_of(client, token, dataset_id)["files"]) == [
            "Returns.csv",
            "Sales 2025-01.csv",
            "Sales 2025-03.csv",
        ]
        assert _tables_of(client, token, dataset_id)["sales_2025"]["files"] == [
            "Sales 2025-01.csv",
            "Sales 2025-03.csv",
        ]

    def test_a_file_over_the_size_limit_is_skipped_with_its_reason(
        self, client, token, dataset_id, sales_folder, monkeypatch
    ):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "max_upload_bytes", 29, raising=False)

        _choose(client, token, dataset_id, sales_folder, _root_rule(False))

        files = _google_of(client, token, dataset_id)["files"]
        statuses = {f["name"]: (f["status"], f["reason"]) for f in files}
        assert statuses["Returns.csv"] == ("skipped", "over the 0 MB limit for one file")
        assert statuses["Sales 2025-01.csv"][0] == "ready"

    def test_a_sheet_over_the_export_limit_is_read_through_the_sheets_api(
        self, client, token, dataset_id, drive, clean_app_db
    ):
        drive.add(SHEET_ID, "Monthly targets", SHEET, sharer=_member_email(clean_app_db))
        drive.tabs[SHEET_ID] = [{"sheetId": 0, "title": "Targets", "sheetType": "GRID"}]
        drive.values[SHEET_ID] = {"Targets": [["dealer", "target"], ["Pune", 12], ["Nashik", 9]]}
        drive.too_big_to_export.add(SHEET_ID)
        link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
        source = _resolve(client, token, dataset_id, link).json()["source"]

        _choose(client, token, dataset_id, source["id"], source["rules"])

        tables = _tables_of(client, token, dataset_id)
        assert ("export", SHEET_ID) in drive.calls
        assert ("values", SHEET_ID) in drive.calls
        assert tables["monthly_targets"]["files"] == ["Monthly targets"]
        assert [c["name"] for c in tables["monthly_targets"]["definition"]["columns"]] == [
            "dealer",
            "target",
            "_source_file",
        ]

    def test_a_sheet_that_exports_is_read_as_a_workbook(
        self, client, token, dataset_id, drive, clean_app_db
    ):
        drive.add(
            SHEET_ID,
            "Monthly targets",
            SHEET,
            sharer=_member_email(clean_app_db),
            content=_sheet_bytes([["dealer", "target"], ["Pune", 12]]),
        )
        drive.tabs[SHEET_ID] = [{"sheetId": 0, "title": "Sheet", "sheetType": "GRID"}]
        link = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
        source = _resolve(client, token, dataset_id, link).json()["source"]

        _choose(client, token, dataset_id, source["id"], source["rules"])

        assert ("values", SHEET_ID) not in drive.calls
        assert "monthly_targets" in _tables_of(client, token, dataset_id)

    def test_only_one_sync_runs_at_a_time(self, dataset_id, sales_folder, drive):
        from sqlalchemy import func

        from app.db.session import _engine
        from app.services import sync

        drive.calls.clear()
        lock = func.hashtext(f"sync:{dataset_id}")
        with _engine.connect() as held:
            held.execute(select(func.pg_advisory_lock(lock)))
            held.commit()

            sync.sync_dataset(dataset_id)

            held.execute(select(func.pg_advisory_unlock(lock)))
            held.commit()

        assert drive.calls == []

    def test_a_question_on_a_stale_dataset_queues_a_sync_and_still_answers(
        self, client, token, dataset_id, sales_folder, clean_app_db, monkeypatch
    ):
        from app.services import sync
        from tests.integration.test_file_connection import _ask

        _choose(client, token, dataset_id, sales_folder, _root_rule(False))
        clean_app_db.execute(
            text("UPDATE connections SET synced_at = now() - interval '2 hours' WHERE id = :id"),
            {"id": dataset_id},
        )
        clean_app_db.commit()
        queued: list[str] = []
        monkeypatch.setattr(sync, "sync_dataset", queued.append)

        events = _ask(client, token, dataset_id, "select count(*) as n from returns", "stale-1")

        assert dict(events)["rows"]["rows"] == [[2]]
        assert queued == [dataset_id]


class TestCombining:
    def test_three_months_share_one_table_and_a_different_file_gets_its_own(
        self, client, token, dataset_id, sales_folder
    ):
        from tests.integration.test_file_connection import _ask

        _choose(client, token, dataset_id, sales_folder, _root_rule(False))

        tables = _tables_of(client, token, dataset_id)
        assert sorted(tables) == ["returns", "sales_2025"]
        assert tables["sales_2025"]["files"] == [f"Sales 2025-{n:02d}.csv" for n in (1, 2, 3)]
        assert tables["sales_2025"]["definition"]["comment"].startswith(
            "Google Drive: Sales 2025, 3 files, synced "
        )
        events = _ask(
            client,
            token,
            dataset_id,
            "select _source_file, sum(units) as units from sales_2025 group by _source_file",
            "union-1",
        )
        assert sorted(dict(events)["rows"]["rows"]) == [
            ["Sales 2025-01.csv", 11],
            ["Sales 2025-02.csv", 22],
            ["Sales 2025-03.csv", 33],
        ]

    def test_a_table_keeps_its_name_when_another_month_arrives(
        self, client, token, dataset_id, sales_folder, drive
    ):
        _choose(client, token, dataset_id, sales_folder, _root_rule(False))
        _month(drive, 4)

        _sync(client, token, dataset_id)

        tables = _tables_of(client, token, dataset_id)
        assert sorted(tables) == ["returns", "sales_2025"]
        assert len(tables["sales_2025"]["files"]) == 4

    def test_without_combining_each_file_is_its_own_table(
        self, client, token, dataset_id, sales_folder
    ):
        _choose(client, token, dataset_id, sales_folder, _root_rule(False), combine=False)

        assert sorted(_tables_of(client, token, dataset_id)) == [
            "returns",
            "sales_2025_01",
            "sales_2025_02",
            "sales_2025_03",
        ]

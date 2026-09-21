import os

import pytest

from app.connectors.gdrive import FOLDER, Drive, kind_of

pytestmark = [
    pytest.mark.integration,
    pytest.mark.google,
    pytest.mark.skipif(
        not os.environ.get("GOOGLE_TEST_FOLDER_ID")
        or not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"),
        reason="needs GOOGLE_TEST_FOLDER_ID and GOOGLE_SERVICE_ACCOUNT_JSON",
    ),
]


def test_a_folder_shared_with_the_service_account_can_be_read():
    folder = os.environ["GOOGLE_TEST_FOLDER_ID"]
    drive = Drive("t_live")

    item = drive.get(folder)
    children = drive.children([folder])

    assert item["mimeType"] == FOLDER
    assert all(folder in child.get("parents", []) for child in children)
    assert {kind_of(child) for child in children} <= {
        "folder",
        "sheet",
        "xlsx",
        "csv",
        "tsv",
        "pdf",
        "other",
    }

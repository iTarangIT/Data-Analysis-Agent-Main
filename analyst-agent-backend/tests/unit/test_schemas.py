import pytest
from pydantic import ValidationError

from app.api.schemas import (
    ConnectionCreate,
    ConnectionOut,
    ProvisionIn,
    RunCreate,
    RunOut,
    TableOut,
    UserOut,
)


class TestConnectionCreate:
    def test_accepts_a_postgres_dsn(self):
        c = ConnectionCreate(name="demo", kind="postgres", secret={"dsn": "postgresql://u:p@h/db"})
        assert c.kind == "postgres"

    def test_rejects_a_postgres_secret_without_a_dsn(self):
        with pytest.raises(ValidationError, match="secret missing"):
            ConnectionCreate(name="demo", kind="postgres", secret={"host": "h"})

    def test_rejects_a_web_dashboard(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(
                name="dash",
                kind="web",
                secret={"url": "https://x", "username": "u", "password": "p"},
            )

    def test_rejects_an_unknown_kind(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(name="x", kind="mysql", secret={"dsn": "d"})

    def test_rejects_a_blank_name(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(name="", kind="postgres", secret={"dsn": "d"})


class TestConnectionOut:
    def test_carries_no_secret_field(self):
        fields = set(ConnectionOut.model_fields)
        assert fields == {
            "id",
            "name",
            "kind",
            "selected_tables",
            "total_tables",
            "file_count",
            "catalog_refreshed_at",
        }
        assert not fields & {"secret", "secret_enc", "dsn", "password"}

    def test_a_file_count_is_required(self):
        with pytest.raises(ValidationError, match="file_count"):
            ConnectionOut(
                id="c",
                name="July",
                kind="file",
                selected_tables=1,
                total_tables=1,
                catalog_refreshed_at=None,
            )


class TestTableOut:
    @pytest.mark.parametrize("file", [None, "Q3 sales.csv"])
    def test_a_table_names_the_file_it_came_from_when_there_is_one(self, file):
        table = TableOut(name="q3_sales", file=file, selected=False, definition=None, stats=None)

        assert table.file == file

    def test_the_file_is_never_left_out(self):
        with pytest.raises(ValidationError, match="file"):
            TableOut(name="q3_sales", selected=False, definition=None, stats=None)


class TestUserOut:
    def test_carries_no_password_field(self):
        fields = set(UserOut.model_fields)
        assert fields == {
            "id",
            "email",
            "name",
            "role",
            "tenant_id",
            "tenant_name",
            "plan",
            "created_at",
        }
        assert not fields & {"password", "password_hash", "hashed_password"}


class TestProvisionIn:
    @pytest.mark.parametrize("name", ["", "   ", "\t\n"])
    def test_an_organisation_needs_a_name_that_is_not_just_space(self, name):
        with pytest.raises(ValidationError):
            ProvisionIn(tenant_name=name)

    def test_a_name_longer_than_the_column_is_refused(self):
        with pytest.raises(ValidationError):
            ProvisionIn(tenant_name="x" * 201)


class TestRunCreate:
    @pytest.mark.parametrize("over", [{}, {"connection_id": None}])
    def test_a_question_must_name_its_connection(self, over):
        with pytest.raises(ValidationError):
            RunCreate(thread_id="t", question="how many dealers", **over)

    @pytest.mark.parametrize("question", ["", "hi"])
    def test_rejects_a_question_that_is_too_short(self, question):
        with pytest.raises(ValidationError):
            RunCreate(connection_id="c", thread_id="t", question=question)

    def test_rejects_a_blank_thread_id(self):
        with pytest.raises(ValidationError):
            RunCreate(connection_id="c", thread_id="", question="how many dealers")


class TestFileConnectionsAreNotCreatedFromABody:
    """`kind="file"` is deliberately absent from the create-connection body.

    Accepting it would mean a client could name the path, and any tenant with a valid token
    could register a connection pointing at an arbitrary local file. No SQL guard could catch
    that, because the path is inside the connector long before any SQL exists. Files arrive
    through `POST /connections/file`, where the server mints every path itself.
    """

    def test_the_body_refuses_a_file_kind(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(name="leak", kind="file", secret={"path": "C:/Windows/win.ini"})

    def test_the_upload_suffixes_are_an_allowlist(self):
        from app.api.schemas import UPLOAD_SUFFIXES

        assert ".exe" not in UPLOAD_SUFFIXES
        assert ".csv" in UPLOAD_SUFFIXES


SAVED_RUN = {
    "id": "r1", "connection_id": "c1", "thread_id": "t1", "question": "How many?",
    "status": "done", "tool": "sql", "sql": "SELECT 1", "answer": "One.", "error": None,
    "model": None, "prompt_tokens": 0, "completion_tokens": 0, "rows_returned": 1,
    "chart": None, "duration_ms": 10, "created_at": "2026-09-18T00:00:00Z",
}  # fmt: skip


class TestRunTrace:
    def test_a_run_from_before_the_trace_has_none(self):
        assert RunOut.model_validate({**SAVED_RUN, "trace": None}).trace is None

    def test_a_stored_trace_reads_back_with_its_attempts(self):
        trace = {
            "stages": ["router", "sql_gen", "sql_guard", "db_exec", "answer"],
            "attempts": [
                {"sql": "SELECT 1", "rejected": False, "what": "Counts.", "why": "Asked.",
                 "rows": 1, "truncated": False, "ms": 4},
            ],
        }  # fmt: skip
        attempt = RunOut.model_validate({**SAVED_RUN, "trace": trace}).trace.attempts[0]
        assert attempt.what == "Counts." and attempt.rows == 1 and attempt.reason is None

    def test_an_unknown_stage_is_refused(self):
        with pytest.raises(ValidationError):
            RunOut.model_validate({**SAVED_RUN, "trace": {"stages": ["guess"], "attempts": []}})

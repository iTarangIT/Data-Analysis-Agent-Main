import pytest
from pydantic import ValidationError

from app.api.schemas import (
    ConnectionCreate,
    ConnectionOut,
    RegisterIn,
    RunCreate,
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


class TestRegisterIn:
    @pytest.mark.parametrize("password", ["", "short", "x" * 11])
    def test_rejects_a_password_that_is_too_short(self, password):
        with pytest.raises(ValidationError):
            RegisterIn(email="a@example.com", password=password)

    def test_rejects_a_password_long_enough_to_be_a_cpu_bomb(self):
        # Argon2 has no input ceiling of its own, so an unbounded password burns 64MiB a go.
        with pytest.raises(ValidationError):
            RegisterIn(email="a@example.com", password="x" * 129)

    def test_rejects_a_malformed_email(self):
        with pytest.raises(ValidationError):
            RegisterIn(email="not-an-email", password="a-long-enough-password")


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

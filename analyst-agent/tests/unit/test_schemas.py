import pytest
from pydantic import ValidationError

from app.api.schemas import ConnectionCreate, ConnectionOut, RunCreate


class TestConnectionCreate:
    def test_accepts_a_postgres_dsn(self):
        c = ConnectionCreate(name="demo", kind="postgres", secret={"dsn": "postgresql://u:p@h/db"})
        assert c.kind == "postgres"

    def test_rejects_a_postgres_secret_without_a_dsn(self):
        with pytest.raises(ValidationError, match="secret missing"):
            ConnectionCreate(name="demo", kind="postgres", secret={"host": "h"})

    def test_rejects_a_web_secret_missing_credentials(self):
        with pytest.raises(ValidationError, match=r"secret missing \['password', 'username'\]"):
            ConnectionCreate(name="dash", kind="web", secret={"url": "https://x"})

    def test_rejects_an_unknown_kind(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(name="x", kind="mysql", secret={"dsn": "d"})

    def test_rejects_a_blank_name(self):
        with pytest.raises(ValidationError):
            ConnectionCreate(name="", kind="postgres", secret={"dsn": "d"})


class TestConnectionOut:
    def test_carries_no_secret_field(self):
        fields = set(ConnectionOut.model_fields)
        assert fields == {"id", "name", "kind", "has_schema_cache"}
        assert not fields & {"secret", "secret_enc", "dsn", "password"}


class TestRunCreate:
    @pytest.mark.parametrize("question", ["", "hi"])
    def test_rejects_a_question_that_is_too_short(self, question):
        with pytest.raises(ValidationError):
            RunCreate(connection_id="c", thread_id="t", question=question)

    def test_rejects_a_blank_thread_id(self):
        with pytest.raises(ValidationError):
            RunCreate(connection_id="c", thread_id="", question="how many dealers")

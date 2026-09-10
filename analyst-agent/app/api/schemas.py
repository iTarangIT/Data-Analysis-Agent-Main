from typing import Literal

from pydantic import BaseModel, Field, field_validator

REQUIRED_SECRET_FIELDS: dict[str, set[str]] = {
    "postgres": {"dsn"},
    "web": {"url", "username", "password"},
}


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["postgres", "web"]
    secret: dict

    @field_validator("secret")
    @classmethod
    def _check_secret(cls, v: dict, info) -> dict:
        kind = info.data.get("kind")
        if kind is None:
            return v  # `kind` already failed validation; its own error is the useful one.
        missing = REQUIRED_SECRET_FIELDS[kind] - v.keys()
        if missing:
            raise ValueError(f"secret missing {sorted(missing)}")
        return v


class ConnectionOut(BaseModel):
    """Deliberately has no secret field. Nothing derived from `secret_enc` may be returned."""

    id: str
    name: str
    kind: str
    has_schema_cache: bool


class RunCreate(BaseModel):
    connection_id: str
    thread_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=3, max_length=2000)

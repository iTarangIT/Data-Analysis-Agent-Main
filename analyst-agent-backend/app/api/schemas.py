from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# A file connection is never created from a client-supplied body: `kind="file"` there would
# let any tenant register a path of their choosing, which no SQL guard could catch, because
# the path is inside the connector long before any SQL exists. Uploads go to /connections/file.
UPLOAD_SUFFIXES = {".csv", ".tsv", ".xlsx", ".parquet"}

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


class ChartSpec(BaseModel):
    """A suggestion rendered beside the table, never instead of it."""

    type: Literal["bar", "line"]
    x: str
    # A list, because one month column beside two numeric ones is the commonest shape a
    # spreadsheet produces, and a list costs nothing.
    y: list[str]


class RunCreate(BaseModel):
    connection_id: str
    thread_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=3, max_length=2000)


class RunOut(BaseModel):
    """A finished or in-flight run. Carries the tenant's own SQL, never anything from the vault."""

    id: str
    connection_id: str
    thread_id: str
    question: str
    status: str
    tool: str | None
    sql: str | None
    error: str | None
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    rows_returned: int
    chart: ChartSpec | None
    duration_ms: int
    created_at: datetime


class UsageDay(BaseModel):
    day: date
    runs: int
    prompt_tokens: int
    completion_tokens: int
    rows_returned: int
    errors: int


class UsageOut(BaseModel):
    daily_token_budget: int
    # The rolling window the 429 refers to. The day buckets below are calendar days, so this
    # is the only field that lines up with an exhausted budget.
    tokens_last_24h: int
    runs_last_24h: int
    days: list[UsageDay]

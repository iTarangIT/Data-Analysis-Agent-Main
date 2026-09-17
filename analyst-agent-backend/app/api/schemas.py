from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.catalog.types import Relationship, TableDef

# A file connection is never created from a client-supplied body: `kind="file"` there would
# let any tenant register a path of their choosing, which no SQL guard could catch, because
# the path is inside the connector long before any SQL exists. Uploads go to /connections/file.
UPLOAD_SUFFIXES = {".csv", ".tsv", ".xlsx", ".parquet"}
MAX_UPLOAD_FILES = 20

REQUIRED_SECRET_FIELDS: dict[str, set[str]] = {
    "postgres": {"dsn"},
}


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["postgres"]
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
    selected_tables: int
    total_tables: int
    file_count: int
    catalog_refreshed_at: datetime | None


class TableOut(BaseModel):
    name: str
    file: str | None
    selected: bool
    # Both null for a table that is not selected: its structure is not kept.
    definition: TableDef | None
    stats: dict[str, Any] | None


class TablesOut(BaseModel):
    max_selected: int
    refreshed_at: datetime | None
    tables: list[TableOut]
    # Between selected tables only.
    relationships: list[Relationship]


class TablesRefreshOut(TablesOut):
    added: list[str]
    removed: list[str]


class TableSelection(BaseModel):
    # The cap is a setting enforced by the service; this only stops an absurd body.
    tables: list[str] = Field(max_length=1000)


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
    # NULL for any run that predates this column, which is why it is not defaulted to "".
    answer: str | None
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


# --- authentication -------------------------------------------------------------------

# Argon2 has no input ceiling of its own, so without a cap a multi-megabyte "password" is a
# free way to burn 64MiB and a CPU core per request.
_Password = Field(min_length=12, max_length=128)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = _Password
    name: str | None = Field(default=None, max_length=200)
    # Signing up creates the tenant, so this names it. Falls back to the email address.
    tenant_name: str | None = Field(default=None, min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class LogoutIn(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)
    all_devices: bool = False


class UserOut(BaseModel):
    """Deliberately has no password field. Nothing derived from `password_hash` may be returned."""

    id: str
    email: str
    name: str | None
    role: str
    tenant_id: str
    tenant_name: str
    plan: str
    created_at: datetime


class AuthOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    # Seconds, so the caller can schedule a refresh without decoding the token, and so the
    # proxy can set a cookie Max-Age without parsing an opaque string.
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    user: UserOut


# --- run history ----------------------------------------------------------------------


class RunSummaryOut(BaseModel):
    """One row of the history list.

    Carries neither `sql`, `answer` nor `error`: all three are unbounded text, and a page of
    fifty would be a heavy payload for what is only a navigation surface. The two booleans let
    the list show what a run produced without shipping it.
    """

    id: str
    thread_id: str
    question: str
    status: str
    tool: str | None
    connection_id: str
    connection_name: str | None
    rows_returned: int
    duration_ms: int
    created_at: datetime
    has_sql: bool
    has_answer: bool


class RunPage(BaseModel):
    items: list[RunSummaryOut]
    # Keyset, not an offset: runs insert at the head of this list, so offset paging would
    # repeat and skip rows while someone reads. None means the end.
    next_cursor: str | None


class ThreadOut(BaseModel):
    """One conversation, for the sidebar."""

    thread_id: str
    # The first question asked, truncated, so the sidebar need not fetch a thread to name it.
    title: str
    run_count: int
    last_run_at: datetime
    last_status: str
    connection_id: str

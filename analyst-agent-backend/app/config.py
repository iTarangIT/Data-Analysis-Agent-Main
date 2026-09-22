import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, PostgresDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = "INFO"

    gemini_api_key: SecretStr
    gemini_model: str = "gemini-3.5-flash-lite"

    app_db_url: PostgresDsn
    checkpoint_db_url: PostgresDsn

    credential_encryption_key: SecretStr
    # Signs the short-lived tokens this service hands its own MCP server. User tokens come
    # from Supabase and are never HMAC-signed.
    jwt_algorithm: str = "HS256"

    # The Supabase project that signs in every user. Sessions, refresh and passwords all live
    # there; this service only verifies its access tokens against the project's public keys.
    supabase_url: str
    # Whether a signed-in Supabase user with no account here may create an organisation.
    allow_open_signup: bool = True

    @field_validator("supabase_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        """The issuer claim is compared as a string, so `https://x.supabase.co/` would reject
        every token."""
        return v.rstrip("/")

    @property
    def supabase_issuer(self) -> str:
        return f"{self.supabase_url}/auth/v1"

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.supabase_issuer}/.well-known/jwks.json"

    # Only reached when a browser talks to this service directly. The Next.js app proxies
    # server-side, so its requests carry no Origin and never touch CORS.
    # NoDecode, or pydantic-settings JSON-parses the env var before the validator runs.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Accept both the JSON list pydantic-settings would otherwise decode and the plain
        comma-separated string anyone actually types into a .env file."""
        if not isinstance(v, str):
            return v
        v = v.strip()
        if v.startswith("["):
            return json.loads(v)
        return [o.strip() for o in v.split(",") if o.strip()]

    max_rows: int = 500
    # How many of a connection's tables a person may let the agent use. Every selected table's
    # structure goes into every query prompt, so this is what bounds that prompt's size.
    max_agent_tables: int = 12
    statement_timeout_ms: int = 8000
    # `statement_timeout` bounds a query once connected; opening the connection is unbounded
    # without this. A source behind a dead SSH tunnel accepts the TCP connection and then never
    # answers, which hung the request and the MCP server with it.
    connect_timeout_s: int = 10

    # The database MCP server. It runs as its own process because it is the only thing that
    # decrypts a customer DSN, and it authenticates with a secret of its own so a leaked user
    # token cannot be replayed against it.
    database_mcp_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8001/mcp")
    mcp_jwt_secret: SecretStr
    mcp_token_ttl_seconds: int = 120
    # Longer than the database's own connect and statement timeouts, so the server's error is
    # what surfaces; this is only the backstop for a server that stops answering entirely.
    mcp_request_timeout_s: int = 30
    # Fail fast at boot rather than on a customer's first question.
    mcp_startup_probe: bool = True
    max_sql_retries: int = 2
    # How many tool calls one question may make. Distinct from max_sql_retries: a model may
    # legitimately query more than once to answer, without any of them having been rejected.
    max_tool_calls: int = 6

    # Forecasting runs a ~200M-parameter model in this process, about a gigabyte resident, which
    # Render's free plan cannot hold. Off, the forecast tool is not offered and nothing loads.
    forecast_engine: Literal["off", "timesfm"] = "off"
    forecast_checkpoint: str = "google/timesfm-2.5-200m-pytorch"
    forecast_threads: int = 2

    # Long-term memory. "postgres" keeps it in the App DB beside the account it belongs to;
    # "memory" keeps it for the life of one process, which is enough for local work and the test
    # suite; "off" attaches no store and runs the agent exactly as it ran before.
    memory_backend: Literal["postgres", "memory", "off"] = "postgres"
    # Old tool results are cleared before the thread is summarised, because clearing costs
    # nothing and summarising costs a model call. A 50-row preview is most of what a long thread
    # holds, so this trips well before the summariser does.
    clear_tool_results_after_tokens: int = 12_000
    # Far below `daily_token_budget`, which is 200,000: without this a single long thread bills
    # the tenant its whole day re-sending its own history.
    summarize_after_tokens: int = 24_000
    # Roughly six question-and-answer turns kept verbatim behind the summary.
    keep_messages: int = 20

    file_store_dir: str = "./uploads"
    file_store_backend: Literal["local", "supabase"] = "local"
    supabase_secret_key: SecretStr | None = None
    storage_bucket: str = "datasets"
    ingest_timeout_s: int = 90
    ingest_memory_mb: int = 2048
    max_pdf_pages: int = 150
    google_service_account_json: SecretStr | None = None
    google_sync_after_minutes: int = 30
    drive_max_depth: int = 5
    drive_max_files: int = 500
    sync_timeout_s: int = 1800
    # Bounds resident memory per concurrent run, because an upload is materialised in full.
    max_upload_bytes: int = 25 * 1024 * 1024
    max_dataset_bytes: int = 100 * 1024 * 1024

    # 127.0.0.1, not localhost: Memurai binds IPv4 only, while `localhost` resolves to ::1
    # first on Windows, so the client spends its whole connect timeout on IPv6 and fails.
    redis_url: RedisDsn = RedisDsn("redis://127.0.0.1:6379/0")
    # Off by default so local development and the test suite need no Redis at all.
    queue_enabled: bool = False
    run_timeout_s: int = 180
    run_heartbeat_s: float = 2.0
    # How long the reader waits with no entry at all before calling the worker dead.
    run_stall_timeout_s: float = 15.0
    run_stream_ttl_s: int = 900
    # Not arq's default of 10: each job holds an App DB session, a checkpoint connection, a
    # store connection and a customer DB connection, against a pool of 5 plus 10 overflow.
    worker_max_jobs: int = 3

    max_runs_per_minute: int = 10
    max_concurrent_runs: int = 3

    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "analyst-agent-dev"
    # Unset keeps the SDK's US default. An EU account's key is refused by that endpoint.
    langsmith_endpoint: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

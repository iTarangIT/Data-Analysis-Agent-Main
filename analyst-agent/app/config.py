from functools import lru_cache

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = "INFO"

    gemini_api_key: SecretStr
    gemini_model: str = "gemini-3.5-flash-lite"

    app_db_url: PostgresDsn
    checkpoint_db_url: PostgresDsn

    credential_encryption_key: SecretStr
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"

    max_rows: int = 500
    # Sample rows are embedded in every SQL-generation prompt. Set to 0 for sources whose row
    # contents must not leave the network.
    schema_sample_rows: int = 3
    statement_timeout_ms: int = 8000
    max_sql_retries: int = 2
    # How many tool calls one question may make. Distinct from max_sql_retries: a model may
    # legitimately query more than once to answer, without any of them having been rejected.
    max_tool_calls: int = 6

    session_store_dir: str = "./sessions"
    file_store_dir: str = "./uploads"
    # Bounds resident memory per concurrent run, because an upload is materialised in full.
    max_upload_bytes: int = 25 * 1024 * 1024
    playwright_headless: bool = True
    # Which of a dashboard's XHR responses carries the data. Narrow it as far as the site
    # allows: every matching body is read, and a wider match can pick up an auth response.
    web_data_url_match: str = "/api/"
    # The Intellicar dashboard pulls in Google Maps, Firebase and reCAPTCHA before it is
    # interactive, and gets slower under repeated sign-ins. 30s was not enough.
    web_nav_timeout_ms: int = 60_000
    # How long to wait for the dashboard's own data call, which only starts after its
    # scripts boot. Waiting is polled, so a fast dashboard does not pay the whole budget.
    web_data_timeout_ms: int = 25_000
    web_settle_ms: int = 1_500

    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")
    # Off by default so local development and the test suite need no Redis at all.
    queue_enabled: bool = False
    run_timeout_s: int = 180
    run_heartbeat_s: float = 2.0
    # How long the reader waits with no entry at all before calling the worker dead.
    run_stall_timeout_s: float = 15.0
    run_stream_ttl_s: int = 900
    # Not arq's default of 10: each job holds an App DB session, a checkpoint connection and a
    # customer DB connection, against a pool of 5 plus 10 overflow.
    worker_max_jobs: int = 4

    max_runs_per_minute: int = 10
    max_concurrent_runs: int = 3

    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "analyst-agent-dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()

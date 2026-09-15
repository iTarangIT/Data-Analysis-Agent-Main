import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator
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
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"

    # Short, because an access token is stateless and cannot be revoked. Logging out kills the
    # refresh token; the access token simply expires.
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    # Two requests that share a session will race to rotate the same refresh token, and the
    # loser would otherwise look like theft and kill the whole family. Inside this window a
    # rotated token is merely rejected. Outside it, it is treated as stolen.
    refresh_reuse_grace_seconds: int = 10
    allow_open_signup: bool = True

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
    # Sample rows are embedded in every SQL-generation prompt. Set to 0 for sources whose row
    # contents must not leave the network.
    schema_sample_rows: int = 3
    statement_timeout_ms: int = 8000
    max_sql_retries: int = 2
    # How many tool calls one question may make. Distinct from max_sql_retries: a model may
    # legitimately query more than once to answer, without any of them having been rejected.
    max_tool_calls: int = 6

    file_store_dir: str = "./uploads"
    # Bounds resident memory per concurrent run, because an upload is materialised in full.
    max_upload_bytes: int = 25 * 1024 * 1024

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

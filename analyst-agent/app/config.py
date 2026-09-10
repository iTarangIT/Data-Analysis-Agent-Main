from functools import lru_cache

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = Field(default="dev", alias="APP_ENV")
    log_level: str = "INFO"

    gemini_api_key: SecretStr
    gemini_model: str = "gemini-3.6-flash"

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
    playwright_headless: bool = True

    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "analyst-agent-dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()

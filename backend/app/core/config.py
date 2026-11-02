"""Application settings loaded from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEV_SECRET = "dev-only-secret-change-me-in-production-0000"  # noqa: S105 - rejected in production below


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "Nustrad ERP"
    log_level: str = "INFO"
    timezone: str = "Asia/Jakarta"
    secret_key: str = DEV_SECRET
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    database_url: str = "postgresql+asyncpg://nustrad:nustrad@localhost:5432/nustrad"
    test_database_url: str = "postgresql+asyncpg://nustrad:nustrad@localhost:5432/nustrad_test"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_access_key: str = "nustrad"
    s3_secret_key: str = "nustrad-secret"  # noqa: S105 - dev MinIO only
    s3_bucket: str = "nustrad-erp"
    s3_region: str = "us-east-1"

    # Auth
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    login_max_failures: int = 5
    login_lock_minutes: int = 30
    refresh_cookie_name: str = "nustrad_refresh"
    totp_issuer: str = "Nustrad ERP"

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    mail_from: str = "Nustrad ERP <no-reply@nustrad.local>"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> "Settings":
        if self.is_production and (self.secret_key == DEV_SECRET or len(self.secret_key) < 32):
            raise ValueError("SECRET_KEY must be set to a random value of 32+ chars in production.")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

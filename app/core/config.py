"""Application settings, loaded from environment variables (a local `.env` file is supported)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "FastAPI SaaS Starter"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    redis_url: str = "redis://localhost:6379/0"

    # No default on purpose: the app refuses to start without a real secret.
    jwt_secret_key: str = Field(min_length=32)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)

    # JSON list in the environment, e.g. CORS_ORIGINS='["http://localhost:4200"]'
    cors_origins: list[str] = []

    @model_validator(mode="after")
    def _reject_placeholder_secret_in_production(self) -> "Settings":
        if self.environment == "production" and "change-me" in self.jwt_secret_key:
            raise ValueError("JWT_SECRET_KEY still contains the example value; set a real secret.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

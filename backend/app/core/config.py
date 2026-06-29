from functools import lru_cache
from typing import List
import json

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    app_name: str = "Enterprise RBAC Platform"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://rbac_user:rbac_password@localhost:5432/rbac_db"

    jwt_secret_key: str = "change-this-to-a-secure-random-secret-key-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    cors_origins: List[str] = ["http://localhost:3000"]

    secure_cookies: bool = False
    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, list):
            return value

        if isinstance(value, str):
            value = value.strip()

            if value.startswith("["):
                return json.loads(value)

            return [origin.strip() for origin in value.split(",")]

        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
from functools import lru_cache
from typing import List
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
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

    # Kept as a raw string (not List[str]): pydantic-settings tries to
    # JSON-decode env vars for list-typed fields before any validator runs,
    # which blows up on a plain comma-separated value like "http://a,http://b".
    cors_origins: str = "http://localhost:3000"

    secure_cookies: bool = False
    log_level: str = "INFO"

    @property
    def cors_origins_list(self) -> List[str]:
        value = self.cors_origins.strip()

        if value.startswith("["):
            return json.loads(value)

        return [origin.strip() for origin in value.split(",") if origin.strip()]

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value):
        """
        Managed Postgres providers (e.g. Render, Neon) hand out URLs using
        the `postgres://`/`postgresql://` scheme and libpq-style query
        params (`sslmode=require`, `channel_binding=require`). asyncpg's
        connect() raises TypeError on any keyword it doesn't recognize, so
        rename `sslmode` to the `ssl` param it does understand and drop
        `channel_binding`, which has no asyncpg equivalent.
        """

        if not isinstance(value, str):
            return value

        if value.startswith("postgres://"):
            value = "postgresql+asyncpg://" + value[len("postgres://"):]

        elif value.startswith("postgresql://"):
            value = "postgresql+asyncpg://" + value[len("postgresql://"):]

        parts = urlsplit(value)
        query = [
            ("ssl" if key == "sslmode" else key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if key != "channel_binding"
        ]

        return urlunsplit(parts._replace(query=urlencode(query)))


@lru_cache
def get_settings() -> Settings:
    return Settings()
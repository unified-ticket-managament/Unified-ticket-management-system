# config.py

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    app_name: str = "Ticket Management System"
    app_env: str = "development"
    debug: bool = False

    api_v1_prefix: str = "/api/v1"

    database_url: str

    log_level: str = "INFO"

    # 👇 Add this
    cors_origins: str = (
        "http://localhost:5173,"
        "http://127.0.0.1:5173,"
        "http://localhost:5174,"
        "http://127.0.0.1:5174,"
        "https://ticket-management-frontend-0t60.onrender.com"
    )

    # Object storage. "supabase" uses Supabase Storage; "s3" uses any
    # S3-compatible host (MinIO locally, Cloudflare R2/AWS S3 in prod).
    # All optional so the app still boots with none set.
    storage_backend: str = "supabase"
    storage_bucket: str = "communication-attachments"
    storage_url_expiry_seconds: int = 3600

    storage_endpoint_url: str | None = None
    storage_access_key: str | None = None
    storage_secret_key: str | None = None
    storage_region: str = "us-east-1"
    storage_use_ssl: bool = False

    supabase_url: str | None = None
    supabase_service_role_key: str | None = None


@lru_cache
def get_settings():
    return Settings()
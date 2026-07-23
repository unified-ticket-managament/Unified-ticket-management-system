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

    app_name: str = "Unified Backend"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # No default: fail fast at boot if the shared secret/DB URL aren't
    # provisioned, rather than silently issuing tokens signed with a
    # well-known placeholder value or connecting to a local throwaway DB.
    database_url: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # In-memory RBAC cache (app/core/rbac_cache.py) — how long a
    # (user_id, permission_version) pair is trusted before the next
    # request re-verifies it against Postgres. This is the bound on
    # how quickly a role change/deactivation/permission change actually
    # takes effect; keep it short relative to access_token_expire_minutes.
    rbac_cache_ttl_seconds: float = 30.0
    # Per-process entry cap (LRU-evicted) — bounds memory, not a
    # correctness knob.
    rbac_cache_max_size: int = 10_000

    # Shared secret for POST /internal/sla/sweep — the Render Cron Job
    # is the only caller, and there's no "user" behind a cron tick to
    # issue it a JWT, so this is a plain shared-secret header instead
    # (same trust model as an API key). No default: fail fast at boot
    # rather than leaving the sweep endpoint reachable with a
    # well-known placeholder value.
    sla_sweep_shared_secret: str

    # How often app/core/sla_scheduler.py's in-process APScheduler job
    # calls SLASweepService.run_sweep() — replaces the old external
    # GitHub Actions cron trigger. The same POST /internal/sla/sweep
    # endpoint (and its shared-secret auth above) stays available for
    # manual/on-demand triggering regardless of this value.
    sla_sweep_interval_minutes: int = 1

    # Kept as a raw string (not List[str]): pydantic-settings tries to
    # JSON-decode env vars for list-typed fields before any validator runs,
    # which blows up on a plain comma-separated value like "http://a,http://b".
    # Union of both original services' dev-default origin lists, so neither
    # frontend loses a currently-allowed origin now that they share one
    # merged default (real deployments override this via env var anyway).
    cors_origins: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "http://localhost:5173,"
        "http://127.0.0.1:5173,"
        "http://localhost:5174,"
        "http://127.0.0.1:5174,"
        "https://ticket-management-frontend-0t60.onrender.com"
    )

    secure_cookies: bool = False
    log_level: str = "INFO"

    # Object storage (ticketing-only). "supabase" uses Supabase Storage;
    # "s3" uses any S3-compatible host (MinIO locally, Cloudflare R2/AWS S3
    # in prod). All optional so the app still boots with none set.
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

    # Real outbound email transport for internal notifications (SLA
    # breach escalations today — see app/core/email_sender.py). All
    # optional: leaving smtp_host unset keeps the app on the existing
    # logging-only fallback, same convention as OutboundDispatcher's
    # own no-op-until-configured behavior for client-facing replies.
    # No specific provider is assumed — any standard SMTP endpoint
    # works (a company mail relay, Gmail/Outlook with an app password,
    # or a local dev catcher like Mailtrap/Mailhog).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_tls: bool = True

    # Absolute base URL of the deployed frontend — used only to build
    # a real clickable link in outbound notification emails (the
    # in-app notification's own `link` field is already relative,
    # which is fine inside the app but useless in an email client).
    # Optional: an unset value just means the email body describes the
    # relative path instead of a clickable URL.
    app_frontend_url: str | None = None

    # Microsoft Graph mail integration (app.ticketing.services.graph_client).
    # All optional, same convention as smtp_* above: get_mail_provider_client()
    # falls back to MockMailProviderClient whenever any of the four
    # identity/mailbox fields is unset, so the app boots and the existing
    # mocked send/receive seam keeps working with no Azure credentials
    # provisioned yet. Once all four are set, that factory switches to the
    # real GraphMailProviderClient automatically — no other code changes.
    graph_tenant_id: str | None = None
    graph_client_id: str | None = None
    graph_client_secret: str | None = None
    graph_mailbox_address: str | None = None
    # Anti-spoofing secret this app itself generates and echoes into every
    # subscription request's clientState — verified against every inbound
    # webhook notification before it's trusted. Required only once a real
    # subscription is created; has no default (never a well-known fallback
    # value for something whose only job is not being guessable).
    graph_webhook_client_state: str | None = None
    graph_api_base_url: str = "https://graph.microsoft.com/v1.0"
    # This app's own externally-reachable HTTPS URL for the incoming
    # route (e.g. "https://unified-backend-xxxx.onrender.com/api/mail/
    # incoming") — a service can't reliably determine its own public
    # URL, especially behind Render, so it's supplied explicitly rather
    # than derived. Only needed for subscription creation/renewal
    # (graph_subscription_service.py); send/fetch don't use it.
    graph_webhook_notification_url: str | None = None

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
# Configuration

All backend configuration is declared in one place: `unified-backend/app/core/config.py`'s `Settings` class (pydantic-settings, reads `.env`, `@lru_cache`d — **restart required for `.env` changes to take effect**).

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `APP_NAME` | "Unified Backend" | no | OpenAPI title |
| `APP_ENV` | "development" | no | Environment tag |
| `DEBUG` | False | no | Also sets SQLAlchemy `echo` |
| `DATABASE_URL` | — | **yes** | Async (asyncpg) connection string; normalized for Neon compatibility |
| `ALEMBIC_DATABASE_URL` | — | yes (for migrations) | Sync (psycopg2) connection string |
| `JWT_SECRET_KEY` | — | **yes** | Shared secret, HS256 |
| `JWT_ALGORITHM` | "HS256" | no | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | no | |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 7 | no | |
| `RBAC_CACHE_TTL_SECONDS` | 30.0 | no | Session cache TTL |
| `RBAC_CACHE_MAX_SIZE` | 10,000 | no | LRU cap |
| `SLA_SWEEP_SHARED_SECRET` | — | **yes** | Protects `POST /internal/sla/sweep` |
| `SLA_SWEEP_INTERVAL_SECONDS` | 10 | no | Sweep cadence — 60 in production |
| `OTP_NLP_CONFIDENCE_THRESHOLD` | 0.90 | no | Confidence (0.0-1.0) the semantic OTP classifier (`app/ticketing/services/otp_classifier.py`) must clear before an inbound email's First Response SLA is completed as a recognized one-time-code delivery. A runtime setting, not a constant the classifier owns — the business rule (what threshold counts as "confident enough") is applied by the caller. Added 2026-08-21. |
| `CORS_ORIGINS` | dev-origins string | no | Comma-separated or JSON list |
| `SECURE_COOKIES` | False | no | |
| `LOG_LEVEL` | "INFO" | no | |
| `STORAGE_BACKEND` | "supabase" | no | "supabase" or "s3" |
| `STORAGE_BUCKET` | "communication-attachments" | no | |
| `STORAGE_URL_EXPIRY_SECONDS` | 3600 | no | Presigned URL TTL |
| `STORAGE_ENDPOINT_URL` / `STORAGE_ACCESS_KEY` / `STORAGE_SECRET_KEY` | None | no | S3-compatible only |
| `STORAGE_REGION` | "us-east-1" | no | |
| `STORAGE_USE_SSL` | False | no | |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | None | no | Supabase-only |
| `SMTP_HOST` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM_EMAIL` | None | no | Unset ⇒ logging-only email fallback |
| `SMTP_PORT` | 587 | no | |
| `SMTP_USE_TLS` | True | no | |
| `APP_FRONTEND_URL` | None | no | Builds clickable links in notification emails |
| `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` / `GRAPH_MAILBOX_ADDRESS` | None | no | All four unset ⇒ mock mail provider |
| `GRAPH_WEBHOOK_CLIENT_STATE` | None | no | Anti-spoofing secret for inbound webhook |
| `GRAPH_API_BASE_URL` | "https://graph.microsoft.com/v1.0" | no | |
| `GRAPH_WEBHOOK_NOTIFICATION_URL` | None | no | This app's own externally-reachable webhook URL |

## Frontend configuration (`unified-frontend/.env.local`)

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | RBAC-domain API base (with `/api/v1`) |
| `NEXT_PUBLIC_TICKETING_API_URL` | Ticketing-domain API base (no `/api/v1`) — **falls back to `http://localhost:8001` if unset**, a stale pre-merge default that silently network-errors every ticketing request; always set this explicitly |
| `NEXT_PUBLIC_TICKETING_FRONTEND_URL` | Declared in `.env.example`/`render.yaml` but confirmed **dead** — nothing in the codebase reads it |

`NEXT_PUBLIC_*` variables are baked in at Next.js build/start time — changing them requires a rebuild/restart, not a hot reload.

## Where `.env.example` files exist

Only **one** exists in the entire repository: `unified-frontend/.env.example` (declaring the three variables above). No `.env.example` exists at the repo root, in `unified-backend/`, or in `ticketing-service/` — see [13-developer-onboarding/environment-variables.md](../13-developer-onboarding/environment-variables.md) for the practical implication (you must construct `unified-backend/.env` from this document, not copy a template).

## Configuration precedence and gotchas

- `Settings` is `@lru_cache`d — a running process never sees a `.env` edit until restarted. `--reload` only reacts to Python file changes, not `.env`.
- Local dev and Render/EC2 both read the identical normalization logic for `DATABASE_URL` — nothing environment-specific there.
- `SLA_SWEEP_INTERVAL_SECONDS` is a genuinely different value between local (10s) and production (60s) by deliberate design — not a bug if you notice the difference.

# Secrets Management

## What secrets this system has

| Secret | Purpose | Where it lives |
|---|---|---|
| `JWT_SECRET_KEY` | Signs/verifies every access and refresh token | `unified-backend/.env` locally; a Render/EC2 environment variable in deployment |
| `SLA_SWEEP_SHARED_SECRET` | Protects the manual `POST /internal/sla/sweep` trigger | Same as above; also mirrored as GitHub repo secrets (`SLA_SWEEP_SHARED_SECRET`) for the manual-fallback workflow |
| `GRAPH_CLIENT_SECRET` | Microsoft Graph OAuth2 client-credentials auth | Environment variable |
| `GRAPH_WEBHOOK_CLIENT_STATE` | Anti-spoofing check for inbound Graph webhook notifications | Environment variable |
| `SUPABASE_SERVICE_ROLE_KEY` | Full-access Supabase Storage credential | Environment variable |
| `STORAGE_SECRET_KEY` | S3-compatible storage credential (if used instead of Supabase) | Environment variable |
| `SMTP_PASSWORD` | Outbound email transport | Environment variable |
| `DATABASE_URL` / `ALEMBIC_DATABASE_URL` | Postgres connection strings (contain embedded credentials) | Environment variable |

## How they're handled

- All secrets are read via `app/core/config.py`'s `Settings` (pydantic-settings, `.env`-backed) — never hardcoded in source.
- `JWT_SECRET_KEY` and `SLA_SWEEP_SHARED_SECRET` have **no default** — the app fails fast at boot if either is missing, rather than silently running insecurely.
- `SLA_SWEEP_SHARED_SECRET` is compared using `secrets.compare_digest` (constant-time comparison) — deliberately resistant to timing attacks, not a naive `==`.
- No secret is ever logged — verify this holds for any new logging statement added near auth/config code (not exhaustively re-audited in this pass).

## Rotation

- **`JWT_SECRET_KEY` rotation is explicitly documented as disruptive** — every currently-issued token becomes invalid immediately (a forced global logout). Root `CLAUDE.md`/`README.md` both call this out as something to schedule deliberately, not a routine change.
- No rotation procedure is documented for any other secret — **not confirmed** whether Graph/Supabase/SMTP credentials are rotated on any schedule.

## What was NOT found (and should not be assumed to exist)

- No secrets-manager integration (AWS Secrets Manager, HashiCorp Vault, etc.) — all secrets are plain environment variables.
- No `.env.example` at the repo root or in `unified-backend/` — only `unified-frontend/.env.example` exists, and it declares no secrets (only public `NEXT_PUBLIC_*` URLs). A new developer must construct `unified-backend/.env` from [13-developer-onboarding/environment-variables.md](../13-developer-onboarding/environment-variables.md), not copy a template.

## Never do this

- Never commit `unified-backend/.env` or any real secret value to git. A prior, unrelated audit found a committed `.env` file and committed `*.tsbuildinfo` build-cache files in `ticketing-service/frontend` (not `unified-backend`/`unified-frontend`) — confirming this class of mistake has happened before in this repository's history. Check `git status`/file contents carefully before any commit touching config files.

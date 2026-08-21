# Environment Variables (Security-Relevant View)

See [05-technical-architecture/configuration.md](../05-technical-architecture/configuration.md) for the complete field list with defaults. This page highlights the security posture of each sensitive category.

## Fail-fast (no default — misconfiguration is loud, not silent)

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `SLA_SWEEP_SHARED_SECRET`

## Safely degrade when unset (no default, but a graceful fallback exists)

- `GRAPH_TENANT_ID`/`GRAPH_CLIENT_ID`/`GRAPH_CLIENT_SECRET`/`GRAPH_MAILBOX_ADDRESS` (all four unset → mock mail provider, no real mailbox access)
- `SMTP_HOST` (unset → logging-only email, no real outbound send)
- `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` (relevant only if `STORAGE_BACKEND=supabase`)

## CORS configuration

`CORS_ORIGINS` — a comma-separated (or JSON-array) string, parsed by `Settings.cors_origins_list`. **In production, this must be set to the real frontend origin(s), not left at the local-dev default** (`http://localhost:3000,http://127.0.0.1:3000` or similar) — an overly permissive value here would allow any origin to make credentialed requests. Verify the deployed value directly; this documentation pass did not have access to the live environment's actual `CORS_ORIGINS`.

## Cookie security

`SECURE_COOKIES` — `false` by default (dev), should be `true` in production (confirmed set in `render.yaml`'s `unified-backend` service). **Not confirmed** whether this setting actually gates any cookie-based mechanism in the current code (the auth model is Bearer-JWT-based, not cookie-based, as far as this pass could confirm) — verify before assuming this flag has an effect.

## The `.env` restart gotcha (an operational security implication)

Because `Settings` is `@lru_cache`d, **rotating a secret in `.env` has no effect until the process restarts**. If a secret is believed compromised, editing `.env` alone does not revoke it — the process must be restarted (and, for `JWT_SECRET_KEY`, every existing token invalidated) for the rotation to take effect.

## Where to find the authoritative, current list

`unified-backend/app/core/config.py`'s `Settings` class is the single source of truth — this document and [05-technical-architecture/configuration.md](../05-technical-architecture/configuration.md) are both snapshots of it as of this documentation pass; re-read the source file directly before making a security-relevant configuration decision.

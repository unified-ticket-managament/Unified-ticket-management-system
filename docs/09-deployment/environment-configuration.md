# Environment Configuration (Deployment Context)

See [05-technical-architecture/configuration.md](../05-technical-architecture/configuration.md) for the complete field-by-field reference. This page covers *where* each path sources its configuration.

## Render (`render.yaml`)

**`unified-backend`** — literal values baked into `render.yaml` (no manual entry needed): `PYTHON_VERSION=3.12.5`, `APP_ENV=production`, `DEBUG="false"`, `SECURE_COOKIES="true"`, `LOG_LEVEL=INFO`, `JWT_ALGORITHM=HS256`, `ACCESS_TOKEN_EXPIRE_MINUTES="30"`, `REFRESH_TOKEN_EXPIRE_DAYS="7"`, `STORAGE_BACKEND=supabase`, `STORAGE_BUCKET=communication-attachments`, `STORAGE_URL_EXPIRY_SECONDS="3600"`, `SLA_SWEEP_INTERVAL_SECONDS="60"`.

Manual (`sync: false`, filled in at Blueprint Apply time): `DATABASE_URL`, `ALEMBIC_DATABASE_URL`, `JWT_SECRET_KEY`, `CORS_ORIGINS`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SLA_SWEEP_SHARED_SECRET`, `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`, `GRAPH_MAILBOX_ADDRESS`, `GRAPH_WEBHOOK_CLIENT_STATE`, `GRAPH_WEBHOOK_NOTIFICATION_URL`. No `generateValue: true` fields exist anywhere in the file — every secret is pasted manually, not Render-generated.

**`unified-frontend`** — literal: `NODE_VERSION=20.18.0`. Manual: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_TICKETING_FRONTEND_URL` (confirmed dead — nothing reads it, see [16-known-limitations](../16-known-limitations/README.md)), `NEXT_PUBLIC_TICKETING_API_URL`.

## EC2 (implied by `.github/workflows/deploy.yml`)

The workflow itself carries no application env vars — it assumes `/opt/utms/unified-backend/.env` and whatever `unified-frontend` needs already exist on the EC2 host, maintained out-of-band (not in this repository). GitHub repository secrets used by the workflow itself: `EC2_HOST`, `EC2_USER`, `EC2_SSH_PRIVATE_KEY` — plus, per root `CLAUDE.md`, `SLA_SWEEP_URL`/`SLA_SWEEP_SHARED_SECRET` for the manual-fallback sweep trigger (kept byte-identical to the backend's own env var).

## Local development

`unified-backend/.env` (git-ignored, hand-constructed — no `.env.example` exists for this directory) and `unified-frontend/.env.local` (same). See [13-developer-onboarding/environment-variables.md](../13-developer-onboarding/environment-variables.md).

## The one thing all three sources must agree on

`JWT_SECRET_KEY` must be identical everywhere a token issued in one environment needs to verify in another — which in practice means it should be **different** per environment (local/EC2/Render each get their own), since tokens are never meant to cross environments. The historical "must match" requirement in root `CLAUDE.md`/`DEPLOYMENT.md` refers to matching *within* one environment's own two (formerly separate) backend services — now moot since there's only one backend process per environment.

# Environments

## Local development

- Backend: `unified-backend`, `.venv`, `bash scripts/start.sh` (or the three commands it wraps), port 8000.
- Frontend: `unified-frontend`, `npm run dev`, port 3000.
- Object storage: MinIO via `docker-compose.yml` (2 services: `minio` + `minio-init`, no Postgres container — the app targets external Neon even locally).
- Database: a Neon project (or Neon branch — see the note below on sharing state with production).

**Real risk, confirmed in root `CLAUDE.md`'s own history**: a developer's local backend and the deployed backend can share the exact same Neon database by default, each running its own independent in-process SLA scheduler — this has genuinely caused a debugging session where a local fix appeared to have no effect because the deployed instance was racing it on the same rows. **Recommendation, also from that same history**: create a Neon branch for local development and point `DATABASE_URL`/`ALEMBIC_DATABASE_URL` at it, rather than coordinating pause/suspend with whoever manages the shared instance.

## "Production" — genuinely ambiguous as of this documentation pass

Two candidate production environments exist in this repository, and this pass could not determine which (if not both) is actually serving real traffic:

1. **Render** (`render.yaml`, 2 web services, free plan). `README.md` and this `render.yaml` are mutually consistent with each other.
2. **EC2** (`.github/workflows/deploy.yml`, SSH + systemd, triggered on every push to `main`). This is the only workflow that fires automatically — a strong signal it's the actively-used path, but not conclusive on its own.

`DEPLOYMENT.md` describes neither of these — it documents an even older, 4-service Render topology that predates the backend consolidation. **Do not follow `DEPLOYMENT.md`'s steps as written.**

## Recommendation

Before making any production-affecting change (env var, migration, secret rotation), confirm with a teammate or the infrastructure owner which environment(s) are live, and check both the Render dashboard and the EC2 host's `systemctl status unified-backend`/`unified-frontend` if in doubt.

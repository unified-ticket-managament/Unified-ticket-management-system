# Deployment Process

## Code → Build → Deploy → Migrate → Restart → Health Check → Verify

### Path A — EC2 (automatic, on push to `main`)

```
git push origin main
  → GitHub Actions: deploy.yml fires
    → SSH into EC2 host
      → git fetch + merge --ff-only origin/main   (fails loudly if diverged)
      → [unified-backend] pip install -r requirements.txt
      → [unified-backend] alembic -c alembic_rbac/alembic.ini upgrade head
      → [unified-backend] alembic -c alembic_ticketing/alembic.ini upgrade head
      → [unified-frontend] npm ci && npm run build
      → systemctl restart unified-backend
      → systemctl restart unified-frontend
      → sleep 5
      → curl 127.0.0.1:8001/health   (job fails if this fails)
```

No manual step is required for this path — it is fully automatic on every push to `main`. **This also means there is no built-in pause for manual verification before the restart** — the health check runs *after* the restart, not as a pre-deploy gate.

### Path B — Render Blueprint (first deploy / manual trigger)

```
Render dashboard: New → Blueprint → select repo/branch
  → Render reads render.yaml, shows 2 services
  → Apply (fill in every sync:false var)
  → unified-backend: pip install -r requirements.txt
      → bash scripts/start.sh
        → alembic -c alembic_rbac/alembic.ini upgrade head
        → alembic -c alembic_ticketing/alembic.ini upgrade head
        → uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
  → unified-frontend: npm ci && npm run build → npm run start
  → healthCheckPath: /health (unified-backend only, per render.yaml)
```

Subsequent deploys happen automatically on push (standard Render Blueprint behavior), or via **Manual Deploy → Deploy latest commit** in the dashboard.

## Local verification before either path

Given neither path pauses for manual verification, the practical gate is: verify locally (`npm run dev` + local backend) before pushing to `main`, since a push both triggers EC2's automatic deploy and (if connected) Render's automatic deploy simultaneously.

## What `DEPLOYMENT.md` describes instead (do not follow)

`DEPLOYMENT.md` documents a 4-service Render Blueprint (`rbac-backend`/`rbac-frontend`/`ticketing-backend`/`ticketing-frontend`) with a manual "circular-dependency second pass" for cross-service URLs. This topology does not match the current `render.yaml` and should be treated as historical/superseded — see [16-known-limitations](../16-known-limitations/README.md).

## First-deploy considerations (Render path, if standing up fresh)

1. Generate `JWT_SECRET_KEY` and `SLA_SWEEP_SHARED_SECRET` (`python -c "import secrets; print(secrets.token_urlsafe(64))"`).
2. Fill in every `sync: false` variable (see [environment-configuration.md](environment-configuration.md)).
3. `CORS_ORIGINS` needs the frontend's real URL — but that URL doesn't exist until the frontend has deployed once. Deploy both services once with a placeholder, then update `CORS_ORIGINS` and redeploy `unified-backend` (env var change alone triggers a restart, no rebuild needed).
4. `NEXT_PUBLIC_*` vars on `unified-frontend` are baked in at build time — any change to them requires **Manual Deploy → Deploy latest commit**, not just saving the env var.

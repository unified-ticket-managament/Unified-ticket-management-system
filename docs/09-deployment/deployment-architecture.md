# Deployment Architecture

See [02-system-architecture/deployment-architecture.md](../02-system-architecture/deployment-architecture.md) for the diagrammed version. This page adds the operational detail an on-call engineer needs.

## Path A — GitHub Actions → EC2 (confirmed to fire automatically)

Trigger: `push` to `main`, or manual `workflow_dispatch`. Concurrency group `production-deploy`, `cancel-in-progress: false` (a second push while one deploy is running queues rather than cancels it).

Steps (all in one job, over SSH):
1. `git fetch` + `git merge --ff-only origin/main` in `/opt/utms` — **fast-forward only**; if the EC2 checkout has diverged (e.g. someone hotfixed directly on the box), this step fails rather than force-overwriting.
2. `unified-backend`: activate `.venv`, `pip install -r requirements.txt`, run both Alembic chains (`upgrade head`).
3. `unified-frontend`: `npm ci && npm run build`.
4. `sudo systemctl restart unified-backend` and `unified-frontend`.
5. Sleep 5 seconds.
6. `curl http://127.0.0.1:8001/health` — **fails the whole job** if this doesn't succeed.

## Path B — Render Blueprint

Each service redeploys independently on a push to the configured branch (standard Render Blueprint behavior) — `buildCommand` then `startCommand` per service (see [infrastructure.md](infrastructure.md) for the exact commands). `scripts/start.sh` (used by the backend's `startCommand`) runs both Alembic chains before `uvicorn`.

## The port discrepancy (worth resolving, not just noting)

- EC2's health check: `127.0.0.1:8001`.
- `render.yaml`/`scripts/start.sh`: default to `8000` (`${PORT:-8000}`).

This means the EC2 host's systemd unit for `unified-backend` must set `PORT=8001` (or an equivalent override) somewhere not visible in this repository — likely the systemd unit file itself, which lives on the EC2 host, not in version control. **If writing a new health-check or monitoring integration, confirm the actual listening port on each environment rather than assuming 8000 everywhere.**

## What decides which path is "real" production

This documentation pass could not determine this from the repository alone. See [environments.md](environments.md).

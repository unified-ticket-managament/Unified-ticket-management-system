# Health Checks

## The endpoint

`GET /health` (`app/main.py`) — unauthenticated, returns a plain `{"status": "healthy"}`. This is a liveness check only — it does **not** verify database connectivity, storage backend reachability, or Graph/SMTP configuration validity. A "healthy" response means the FastAPI process is up and routing requests, nothing more.

## Where it's actually checked

| Path | Check | Port |
|---|---|---|
| EC2 (`deploy.yml`) | `curl http://127.0.0.1:8001/health`, after a 5s sleep post-restart — **fails the deploy job** if unsuccessful | 8001 |
| Render (`render.yaml`) | `healthCheckPath: /health` on the `unified-backend` service — Render's own platform-level health check, used for zero-downtime deploys and to decide whether to keep serving the old instance | Whatever `$PORT` Render assigns (default 8000 per `start.sh`) |

**These check different ports** — see [deployment-architecture.md](deployment-architecture.md) for the discrepancy and what it implies about the EC2 host's actual `PORT` configuration.

## What a "healthy" response does NOT tell you

- Whether the SLA sweep scheduler actually started (`start_scheduler()` could theoretically fail silently at startup — verify via logs, not `/health`).
- Whether Postgres is reachable (a DB-touching request would fail even with `/health` green, if the connection pool can't reach Neon).
- Whether Microsoft Graph credentials are valid (an expired/revoked Graph app secret degrades mail intake silently, not via `/health`).

## Recommended operational checks beyond `/health`

- `GET /docs` reachable → confirms the app started far enough to build its OpenAPI schema.
- A real authenticated request (e.g. `GET /tickets/view-counts`) → confirms DB connectivity end-to-end, not just process liveness.
- Check logs for `Scheduled SLA sweep completed` lines appearing on the expected cadence → confirms the in-process scheduler is genuinely running, not just that the process started.
- See [10-operations/system-health.md](../10-operations/system-health.md) for the fuller day-to-day operational checklist.

## The `--reload`/stale-process trap (relevant to health checks specifically)

Root `CLAUDE.md` documents a real, twice-confirmed incident where a backend process appeared to reload successfully (`WatchFiles detected changes... Reloading...` printed) but the actual listening worker still predated a fix — `/health` would have reported healthy throughout, since the *process* never actually died. The only reliable check in that scenario was comparing the worker process's own start time against the edited file's mtime, or hitting the actual route with `curl`/`httpx` rather than trusting the reload log line or `/health` alone.

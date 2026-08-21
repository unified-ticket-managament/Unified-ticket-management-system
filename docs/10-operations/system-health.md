# System Health

## What "healthy" means, component by component

| Component | Healthy signal | How to check |
|---|---|---|
| Backend process | `GET /health` returns 200 | Direct HTTP call |
| Database connectivity | An authenticated DB-touching request succeeds | `GET /tickets/view-counts` with a valid token |
| SLA scheduler | `Scheduled SLA sweep completed` log lines at the expected cadence | Log inspection — **`/health` does not confirm this** |
| Microsoft Graph mail intake | New client email produces new `interactions` rows within a reasonable window | DB query or UI check |
| Notification SSE | An open `/notifications/stream` connection receives events in real time | Browser DevTools Network tab, or `curl -N` |
| Outbound email | A business-critical notification produces a real email, not just an in-app row | Manual spot-check against a real inbox |

## The stale-process trap (a documented, twice-confirmed incident class)

`uvicorn --reload` can print `WatchFiles detected changes... Reloading...` and look successful while the actual listening worker still predates the fix. The only reliable confirmation: compare the worker process's own start time against the edited file's mtime, or exercise the real route (not the service method directly, which bypasses routing/CORS and can pass while the live route still fails).

**On Windows specifically**: killing the PIDs `uvicorn` reports doesn't reliably clean up — orphaned `python.exe` processes and stale `Listen`-state socket entries can survive `taskkill /F`. The reliable sequence: kill every python/uvicorn process → confirm `Get-NetTCPConnection -LocalPort 8000` (or the relevant port) returns nothing → start exactly one fresh process → compare start time against edited file mtimes → mint a real token and hit the actual route.

## The shared-database racing-scheduler trap

A locally-running backend and a deployed instance can point at the same Neon database, each running an independent in-process SLA scheduler — a local fix to escalation/SLA timing can appear to have zero effect because the deployed instance keeps winning the race on the same rows. Confirm via the deployed environment's own logs (`Scheduled SLA sweep completed` lines) before concluding a local fix is broken. See [09-deployment/environments.md](../09-deployment/environments.md) for the recommended fix (a Neon branch for local dev).

## Health check limitations to keep in mind

`GET /health` is a pure liveness check — see [09-deployment/health-checks.md](../09-deployment/health-checks.md) for exactly what it does and doesn't verify, and the confirmed port mismatch between the two deployment paths' own health-check configurations.

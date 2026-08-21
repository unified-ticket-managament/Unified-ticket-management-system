# Monitoring

## What exists today

- `Server-Timing` HTTP response header (`ServerTimingMiddleware`, `app/main.py`) — exposes `total`, `db`, and named stages (e.g. `auth`) per request. This is real, low-level per-request instrumentation, inspectable via browser DevTools or `curl -I`, but it is not aggregated or stored anywhere — it's a point-in-time diagnostic, not a monitoring dashboard.
- `structlog`/stdlib `logging` — configured once (`logging.basicConfig` in `main.py`, `LOG_LEVEL` from `Settings`). Where these logs are shipped (stdout only? a log aggregator?) depends on the hosting platform (Render's own log viewer, or however the EC2 host's systemd journal is configured) — **not confirmed** by this documentation pass.
- Render's own dashboard **Logs** tab — explicitly referenced in root `CLAUDE.md` as the way to check whether a Render-hosted `unified-backend` instance is still processing SLA sweeps (`Scheduled SLA sweep completed` lines), even after attempting to suspend it.

## What was NOT found

- No APM integration (Datadog, New Relic, Sentry, etc.) anywhere in `requirements.txt` or `package.json`.
- No structured metrics export (Prometheus, StatsD).
- No dashboard aggregating `Server-Timing` data over time.
- No uptime-monitoring configuration (Pingdom, UptimeRobot, etc.) found in the repository — though one could exist purely in a third-party dashboard with no repository footprint, which this pass can't rule out.

## What this means operationally

Observability today is **log-based and manual** — an incident is diagnosed by reading logs directly (Render's Logs tab, or the EC2 host's `journalctl`/systemd logs) and, where needed, reproducing the exact failing call in isolation (a pattern root `CLAUDE.md` recommends repeatedly: "reproduce the exact service-layer call directly in a throwaway script, bypassing FastAPI/HTTP entirely, to get the real traceback").

## Recommendation

If this system scales beyond its current single-process-per-environment model, real monitoring (error rate, latency percentiles, SLA-sweep-tick success rate as its own metric) would be a valuable addition — not present today.

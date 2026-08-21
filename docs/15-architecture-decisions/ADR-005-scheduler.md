# ADR-005: In-Process APScheduler, Not External Cron

**Status**: Accepted (implemented, in production use) — superseded an earlier design

## Context

The SLA sweep needs to run periodically (every 10-60 seconds) to evaluate every active clock against its breach thresholds. Render's free tier has no usable `type: cron` service (Render Cron Jobs require a paid plan).

## Problem

How should this periodic sweep actually be triggered in production?

## Options Considered

1. **GitHub Actions scheduled workflow** (`schedule:` trigger) calling a shared-secret-protected internal endpoint (`POST /internal/sla/sweep`) — this is what the system **originally did**.
2. **In-process scheduler** (APScheduler) wired into the FastAPI app's own `lifespan` hook, running inside the same running backend process.

## Decision

Option 2 — `app/core/sla_scheduler.py`'s `AsyncIOScheduler`, firing on `SLA_SWEEP_INTERVAL_SECONDS`.

## Reason

GitHub Actions' scheduled workflows have a documented minimum practical interval (and reliability characteristics) far coarser than the 10-60 second cadence this feature needs — good enough for a once-daily job, not for near-real-time SLA breach detection. Moving the trigger in-process removes the external dependency and the network round trip entirely for the common case.

## Trade-offs

- **Cost**: the sweep is now tied to the backend process's own lifecycle — if the process is down, sweeps simply don't happen (no external system to notice and retry), whereas a GitHub Actions cron would have kept trying independently of the app's own uptime.
- **Cost**: `max_instances=1`/`coalesce=True` are needed to guard against overlapping ticks if one run takes longer than the interval — a class of bug that wasn't possible with the old once-per-invocation external trigger.
- **Benefit**: zero external secret-sharing/network-call overhead for the routine case.
- **Benefit**: local development gets fast, realistic sweep behavior (10s default) with no external service needed at all.

## Consequences

The GitHub Actions workflow's `schedule:` trigger was removed; `workflow_dispatch: {}` was deliberately kept as a manual/emergency fallback, and `POST /internal/sla/sweep` remains reachable (shared-secret-protected) for that purpose — this is a real, intentional redundancy, not leftover cruft. **Note**: this documentation pass could not find an actual `sla-sweep.yml` file in `.github/workflows/` (only `deploy.yml` exists) — the manual-fallback workflow file referenced by `render.yaml`'s own comments appears to have been removed at some point after being described, a real, confirmed drift worth investigating if the manual fallback is ever needed. See [16-known-limitations](../16-known-limitations/README.md).

## Related Components

`app/core/sla_scheduler.py`, `app/ticketing/api/sla_internal.py`, `app/ticketing/services/sla_sweep_service.py`.

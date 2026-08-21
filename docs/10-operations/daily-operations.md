# Daily Operations

No automated daily-operations tooling (a cron report, a Slack digest, etc.) was found in this repository. The checks below are what a human would need to do manually, derived from what the system actually depends on.

## Quick daily checklist

1. **Backend liveness**: `GET /health` on whichever environment is live (see [09-deployment/environments.md](../09-deployment/environments.md)).
2. **SLA sweep is actually running**: check backend logs for `Scheduled SLA sweep completed` lines on the expected cadence (every 60s in production, per `SLA_SWEEP_INTERVAL_SECONDS`). Its absence, or its presence when you expect the service to be suspended, is the single most reliable signal for the "two schedulers racing on the same database" class of incident documented in root `CLAUDE.md`.
3. **Mail intake**: confirm new inbound email is still creating `interactions` rows (a query against the dev/prod database, or simply confirming new Mail items appear in the Inbox UI) — a lapsed Microsoft Graph webhook subscription or an expired client secret degrades this silently, with only a log line to show for it.
4. **Notification email delivery**: if SMTP is configured, spot-check that a recent business-critical notification (ticket assignment, escalation) actually produced an email, not just an in-app row — this feature is unit-tested but was **not confirmed live-verified against real SMTP** in the codebase's own history, per root `CLAUDE.md`.
5. **Escalation queue isn't silently stuck**: check the Escalated tab for tickets whose `ack_due_at` has long since passed with no advance — this would indicate the sweep's `evaluate_overdue` step isn't running, or is erroring per-ticket in a way the SAVEPOINT isolation doesn't catch (a real, previously-encountered failure mode).

## Weekly / periodic checks

- Confirm both Alembic chains are at head in whichever database is live (`alembic ... current` vs `heads`) — a stale schema has repeatedly masked itself as a logic bug in this codebase's history.
- Review recently-created `ticket_escalations` rows still `ACTIVE` after an unusually long time — may indicate a category with no configured Team Lead (the fallback-walk mechanism handles zero-owner cases, but worth knowing when it's triggering).
- Spot-check the connection pool isn't saturating (`pool_size=20, max_overflow=30`) under normal load — see [16-known-limitations/performance-limitations.md](../16-known-limitations/performance-limitations.md) for why this number was chosen and when to reconsider it.

## What doesn't need daily attention

- Migrations — applied automatically as part of every deploy on both paths.
- The SLA sweep itself — runs unattended; only its *absence* needs investigating.

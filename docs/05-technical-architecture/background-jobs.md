# Background Jobs

All background work runs **in-process**, wired into the FastAPI `lifespan` hook — there is no separate worker process to deploy or monitor.

## SLA Sweep

| Aspect | Detail |
|---|---|
| Scheduler | `AsyncIOScheduler` (APScheduler), module-level singleton in `app/core/sla_scheduler.py` |
| Trigger | `add_job(_run_scheduled_sweep, trigger="interval", seconds=settings.sla_sweep_interval_seconds, id="sla_sweep", max_instances=1, coalesce=True, replace_existing=True)` |
| Interval | `SLA_SWEEP_INTERVAL_SECONDS` — default 10 (local), overridden to 60 in production (`render.yaml`) |
| Started/stopped | `start_scheduler()`/`shutdown_scheduler()`, called from `main.py`'s lifespan; both idempotent |
| DB session | Opens its own `AsyncSessionLocal()` — no request context |
| Manual fallback | `POST /internal/sla/sweep`, shared-secret protected (`X-SLA-Sweep-Secret`, `secrets.compare_digest`) |
| What it does | See [03-business-workflows/sla/sla-breach.md](../03-business-workflows/sla/sla-breach.md) |

`max_instances=1`/`coalesce=True` guard against overlapping ticks if one run takes longer than the interval — a tick that's still running when the next one would fire is coalesced rather than stacking.

## Microsoft Graph webhook subscription lifecycle

| Aspect | Detail |
|---|---|
| Scheduler | `app/core/graph_subscription_scheduler.py` |
| What it does | Creates/renews the Graph webhook subscription that delivers inbound mail change notifications to `POST /api/mail/incoming` |
| Depends on | `GRAPH_WEBHOOK_NOTIFICATION_URL` being a real, externally-reachable HTTPS URL |

## Microsoft Graph mail polling (fallback)

| Aspect | Detail |
|---|---|
| Scheduler | `app/core/graph_mail_poll_scheduler.py` |
| What it does | Polls each configured mailbox for new mail since its last checkpoint — the fallback transport for local dev (no public webhook URL) or if the webhook subscription lapses |
| First-run lookback | 15 minutes (`INITIAL_LOOKBACK_MINUTES`) |
| State | Per-mailbox checkpoints held in an in-process `_PollState` — **not persisted**, resets on restart |

## What's deliberately NOT a separate process

- No Celery/RQ/dedicated task-queue worker exists.
- The email-notification dispatch (`email_notifier.queue_notification_emails`) is a fire-and-forget `asyncio.create_task` within the same process, not a queued job — see [04-functional-modules/notification-management.md](../04-functional-modules/notification-management.md).
- A prior local-dev workaround script (`scripts/sla_sweep_local_loop.py`) was deleted once the in-process scheduler made it redundant.

## Operational implications

- Since everything is in-process, **restarting the backend restarts every scheduled job** — there's no separate lifecycle to manage.
- A poll-state checkpoint resets on every restart, meaning a restart could re-fetch up to the lookback window's worth of mail — deduplication by `message_id` is what prevents this from creating duplicate Interactions (see [03-business-workflows/communication/incoming-email.md](../03-business-workflows/communication/incoming-email.md)).
- See [10-operations/system-health.md](../10-operations/system-health.md) for how to confirm these jobs are actually running in a given environment.

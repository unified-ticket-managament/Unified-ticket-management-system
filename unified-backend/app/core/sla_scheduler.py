import logging
import os
import uuid

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.database.session import AsyncSessionLocal
from app.ticketing.api.sla_internal import build_sla_sweep_service

#sla_scheduler.py

logger = logging.getLogger(__name__)

SLA_SWEEP_JOB_ID = "sla_sweep"

# Identifies which process is ticking, in logs — Render sets
# RENDER_INSTANCE_ID automatically on every deployed instance; a local
# dev process has neither, so it gets its own generated id instead.
# Exists purely so a deployed instance and a local dev instance (both
# capable of running this same in-process scheduler against the same
# shared Neon database — see root CLAUDE.md's Deployment section) can
# be told apart by comparing their own "SLA sweep scheduler started"/
# "Scheduled SLA sweep completed" log lines side by side, rather than
# guessing whether a reported "missing notification" was actually sent
# by the other process. Computed once at import time, not per call.
SLA_SWEEP_PROCESS_ID = os.environ.get("RENDER_INSTANCE_ID") or f"local-{uuid.uuid4().hex[:8]}"

# Module-level singleton — Python only executes a module's top-level
# code once per process no matter how many places import it, so this
# is created exactly once regardless of import order/count. Same
# pattern this codebase already uses for `engine`/`AsyncSessionLocal`
# in app/database/session.py.
scheduler = AsyncIOScheduler()


async def _run_scheduled_sweep() -> None:
    """
    The APScheduler job body. Runs with no HTTP request and therefore
    no Depends(get_db) — opens its own session directly from
    AsyncSessionLocal (the same factory get_db() itself wraps) and
    replicates get_db()'s own commit-on-success/rollback-on-error
    semantics by hand, since this path doesn't go through that
    dependency. Builds the service via build_sla_sweep_service() (see
    api/sla_internal.py) — the exact same wiring the manual endpoint
    uses — and calls nothing but SLASweepService.run_sweep() itself;
    no SLA/escalation/notification logic lives here.
    """

    async with AsyncSessionLocal() as db:
        try:
            service = build_sla_sweep_service(db)
            result = await service.run_sweep()
            await db.commit()
            logger.info(
                "Scheduled SLA sweep completed [process=%s]: %s",
                SLA_SWEEP_PROCESS_ID,
                result,
            )
        except Exception:
            await db.rollback()
            logger.exception(
                "Scheduled SLA sweep failed [process=%s]", SLA_SWEEP_PROCESS_ID
            )


def start_scheduler() -> None:
    """
    Idempotent — safe to call more than once in the same process (a
    second call is a no-op) so an accidental double-invocation of the
    lifespan startup hook can never produce two competing schedulers.

    Reads its interval from settings.sla_sweep_interval_minutes (see
    app/core/config.py's own docstring on that field, which already
    claimed this scheduler reads it — it didn't, until now: this was
    hardcoded to a flat 10 seconds regardless of that setting, six
    times more frequent than the documented 1-minute default). Beyond
    just matching the docs, this matters because a shorter interval
    directly multiplies how often two independently-running processes
    (a deployed instance and a local dev instance, both capable of
    running this same in-process scheduler against the same shared
    Neon database — see root CLAUDE.md's Deployment section) can land
    on the same clock/threshold at nearly the same moment and race on
    SLABreachNotificationRepository.try_record_many's idempotency
    ledger — only one of them ever gets to actually send that
    notification, and the loser silently never retries it.
    """

    if scheduler.running:
        return

    interval_minutes = get_settings().sla_sweep_interval_minutes

    scheduler.add_job(
        _run_scheduled_sweep,
        trigger="interval",
        minutes=interval_minutes,
        id=SLA_SWEEP_JOB_ID,
        # APScheduler's own overlap guard — if a sweep is still running
        # when the next tick fires, the new tick is skipped rather than
        # started concurrently, rather than relying solely on the
        # database-level idempotency SLASweepService already has.
        max_instances=1,
        # A process that was suspended/blocked through several missed
        # ticks runs once when it resumes, not once per missed tick.
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    # process=%s is the whole point of this line existing: compare it
    # against another environment's own startup log (e.g. Render's
    # dashboard Logs tab vs local dev) to find out whether two
    # processes are actually both ticking against the same database —
    # see this function's own docstring.
    logger.info(
        "SLA sweep scheduler started [process=%s] — running every %s minute(s).",
        SLA_SWEEP_PROCESS_ID,
        interval_minutes,
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("SLA sweep scheduler stopped.")

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.database.session import AsyncSessionLocal
from app.ticketing.api.sla_internal import build_sla_sweep_service

#sla_scheduler.py

logger = logging.getLogger(__name__)

SLA_SWEEP_JOB_ID = "sla_sweep"

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
            logger.info("Scheduled SLA sweep completed: %s", result)
        except Exception:
            await db.rollback()
            logger.exception("Scheduled SLA sweep failed")


def start_scheduler() -> None:
    """
    Idempotent — safe to call more than once in the same process (a
    second call is a no-op) so an accidental double-invocation of the
    lifespan startup hook can never produce two competing schedulers.
    """

    if scheduler.running:
        return

    settings = get_settings()

    scheduler.add_job(
        _run_scheduled_sweep,
        trigger="interval",
        minutes=settings.sla_sweep_interval_minutes,
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
    logger.info(
        "SLA sweep scheduler started — running every %d minute(s).",
        settings.sla_sweep_interval_minutes,
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("SLA sweep scheduler stopped.")

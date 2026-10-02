import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database.session import AsyncSessionLocal
from app.ticketing.services.rule_run_worker import run_worker_tick

logger = logging.getLogger(__name__)

RULE_RUN_JOB_ID = "rule_run_worker"

# How often the worker looks for queued/resumable "Run rule now" runs,
# and how long one tick may keep working a run before yielding (the next
# tick resumes it from its persisted cursor).
RULE_RUN_INTERVAL_SECONDS = 15
RULE_RUN_TICK_BUDGET_SECONDS = 40

scheduler = AsyncIOScheduler()


async def _run_tick() -> None:
    try:
        await run_worker_tick(AsyncSessionLocal, budget_seconds=RULE_RUN_TICK_BUDGET_SECONDS)
    except Exception:
        logger.exception("Rule run worker tick failed")


def start_scheduler() -> None:
    """Idempotent — safe to call more than once in the same process."""

    if scheduler.running:
        return

    # max_instances=1/coalesce=True: a tick still working a run is never
    # overlapped by the next one — same guard as the SLA sweep.
    scheduler.add_job(
        _run_tick,
        trigger="interval",
        seconds=RULE_RUN_INTERVAL_SECONDS,
        next_run_time=datetime.now(),
        id=RULE_RUN_JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Rule run worker scheduler started — checking every %s seconds.",
        RULE_RUN_INTERVAL_SECONDS,
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Rule run worker scheduler stopped.")

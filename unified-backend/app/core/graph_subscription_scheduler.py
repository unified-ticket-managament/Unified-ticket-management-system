# graph_subscription_scheduler.py
#
# In-process periodic trigger for the Graph subscription create/renew
# check (app/ticketing/services/graph_subscription_service.py) — mirrors
# app/core/sla_scheduler.py's own shape exactly (module-level scheduler
# singleton, idempotent start/shutdown, own DB-free job body) rather
# than introducing a second scheduling mechanism. A no-op tick whenever
# Graph isn't fully configured (ensure_subscription() itself checks
# this), so running this scheduler unconditionally is safe even with
# no Azure credentials provisioned.

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.ticketing.services.graph_subscription_service import ensure_subscription

logger = logging.getLogger(__name__)

GRAPH_SUBSCRIPTION_JOB_ID = "graph_subscription_check"

# Module-level singleton — see sla_scheduler.py's identical comment on
# why this is safe regardless of import order/count.
scheduler = AsyncIOScheduler()


async def _run_subscription_check() -> None:
    try:
        await ensure_subscription(get_settings())
    except Exception:
        logger.exception("Graph subscription check failed")


def start_scheduler() -> None:
    """Idempotent — safe to call more than once in the same process."""

    if scheduler.running:
        return

    scheduler.add_job(
        _run_subscription_check,
        trigger="interval",
        # Well inside RENEWAL_MARGIN_MINUTES (1 day) and far inside
        # SUBSCRIPTION_LIFETIME_MINUTES (~3 days), so a subscription is
        # never at real risk of lapsing between ticks.
        hours=1,
        # APScheduler's own default for an interval trigger is to fire
        # for the first time one full interval *after* the job is
        # added — i.e. an hour after every process start, not
        # immediately. That would mean a freshly-configured Graph
        # integration (or a plain restart) waits up to an hour before
        # the very first subscription-creation attempt. Forcing the
        # first run to "now" means credentials added and the process
        # restarted take effect on the very next request cycle, not
        # up to an hour later.
        next_run_time=datetime.now(),
        id=GRAPH_SUBSCRIPTION_JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Graph subscription scheduler started — checking every hour.")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Graph subscription scheduler stopped.")

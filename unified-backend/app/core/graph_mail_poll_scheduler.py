# graph_mail_poll_scheduler.py
#
# In-process periodic trigger for the Graph mail-polling check
# (app/ticketing/services/graph_mail_poller.py) — mirrors
# sla_scheduler.py/graph_subscription_scheduler.py's own shape exactly.
# A no-op tick whenever Graph isn't fully configured for send/fetch
# (poll_new_messages() itself checks this), so running this scheduler
# unconditionally is safe with no Azure credentials provisioned.

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.ticketing.services.graph_mail_poller import poll_new_messages

logger = logging.getLogger(__name__)

GRAPH_MAIL_POLL_JOB_ID = "graph_mail_poll"

# Module-level singleton — see sla_scheduler.py's identical comment on
# why this is safe regardless of import order/count.
scheduler = AsyncIOScheduler()


async def _run_poll() -> None:
    try:
        await poll_new_messages(get_settings())
    except Exception:
        logger.exception("Graph mail poll tick failed")


def start_scheduler() -> None:
    """Idempotent — safe to call more than once in the same process."""

    if scheduler.running:
        return

    scheduler.add_job(
        _run_poll,
        trigger="interval",
        minutes=1,
        # Same "run immediately, not after the first interval" fix as
        # graph_subscription_scheduler.py — otherwise a freshly-
        # configured integration or a plain restart waits a full
        # minute (small here, but the principle matters more once this
        # value is ever raised) before the first poll.
        next_run_time=datetime.now(),
        id=GRAPH_MAIL_POLL_JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Graph mail poll scheduler started — polling every minute.")


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Graph mail poll scheduler stopped.")

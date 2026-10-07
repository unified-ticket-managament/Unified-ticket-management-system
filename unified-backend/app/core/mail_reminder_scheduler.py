import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.database.session import AsyncSessionLocal
from app.ticketing.services.mail_reminder_service import run_due_reminders_sweep

# mail_reminder_scheduler.py
#
# Fires due "Remind me" reminders as MAIL_REMINDER_DUE notifications.
# Same APScheduler wiring shape as rule_run_scheduler.py. Multi-process
# safety does NOT come from max_instances (that is per process): every
# due reminder is claimed with FOR UPDATE SKIP LOCKED and marked FIRED in
# the same transaction as its notification (see mail_reminder_service.
# process_one_due_reminder), so two processes can never both fire one.

logger = logging.getLogger(__name__)

MAIL_REMINDER_JOB_ID = "mail_reminder_sweep"

scheduler = AsyncIOScheduler()


def is_enabled() -> bool:
    settings = get_settings()
    if settings.mail_reminder_scheduler_enabled is not None:
        return settings.mail_reminder_scheduler_enabled
    return settings.app_env.strip().lower() in ("production", "prod")


async def _run_sweep() -> None:
    try:
        handled = await run_due_reminders_sweep(AsyncSessionLocal)
        if handled:
            logger.info("Mail reminder sweep handled %s reminder(s).", handled)
    except Exception:
        logger.exception("Mail reminder sweep failed")


def start_scheduler() -> None:
    """Idempotent — safe to call more than once in the same process."""

    if scheduler.running:
        return

    if not is_enabled():
        logger.info(
            "Mail reminder scheduler disabled for this process "
            "(APP_ENV is not production and MAIL_REMINDER_SCHEDULER_ENABLED is unset)."
        )
        return

    interval = get_settings().mail_reminder_sweep_interval_seconds
    scheduler.add_job(
        _run_sweep,
        trigger="interval",
        seconds=interval,
        next_run_time=datetime.now(),
        id=MAIL_REMINDER_JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Mail reminder scheduler started — checking every %s seconds.", interval)


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Mail reminder scheduler stopped.")

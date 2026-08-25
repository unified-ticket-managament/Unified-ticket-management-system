import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.database.session import AsyncSessionLocal
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.storage import get_storage_service
from app.ticketing.storage.base import StorageConfigurationError

#draft_retention_scheduler.py
#
# Phase 2 hardening: sweeps abandoned drafts and abandoned pasted
# inline images (see InteractionRepository.list_stale_drafts /
# list_stale_unclaimed_inline_images, and InteractionService.
# _discard_draft_core / _discard_stale_inline_image) — the scheduled
# counterpart to the interactive discard_draft action, for whatever a
# user never explicitly discarded (tab closed, crash, navigated away).
# Mirrors app/core/sla_scheduler.py's exact APScheduler wiring shape.

logger = logging.getLogger(__name__)

DRAFT_RETENTION_JOB_ID = "draft_retention_sweep"

scheduler = AsyncIOScheduler()


def _build_interaction_service(db) -> InteractionService:
    try:
        storage_service = get_storage_service()
    except StorageConfigurationError:
        # An unconfigured storage backend still allows the sweep to run
        # — it just can't delete storage objects (InteractionService.
        # _delete_stored_attachments no-ops without one), same
        # tradeoff outbound_dispatcher.py already accepts.
        storage_service = None

    return InteractionService(
        interaction_repository=InteractionRepository(db),
        ticket_repository=TicketRepository(db),
        user_repository=UserRepository(db),
        attachment_repository=AttachmentRepository(db),
        storage_service=storage_service,
    )


async def _run_draft_retention_sweep() -> None:
    """
    The APScheduler job body. Runs with no HTTP request and therefore
    no Depends(get_db) — opens its own session directly from
    AsyncSessionLocal, same pattern app/core/sla_scheduler.py's own
    _run_scheduled_sweep already uses.
    """

    async with AsyncSessionLocal() as db:
        try:
            settings = get_settings()
            cutoff = datetime.now(timezone.utc) - timedelta(
                days=settings.draft_retention_days
            )
            interaction_repository = InteractionRepository(db)
            service = _build_interaction_service(db)

            stale_drafts = await interaction_repository.list_stale_drafts(cutoff)
            for draft in stale_drafts:
                await service._discard_draft_core(draft)

            stale_inline_images = await interaction_repository.list_stale_unclaimed_inline_images(
                cutoff
            )
            for interaction in stale_inline_images:
                await service._discard_stale_inline_image(interaction)

            await db.commit()
            logger.info(
                "Draft retention sweep completed: %d draft(s), %d inline "
                "image(s) removed (older than %d day(s)).",
                len(stale_drafts),
                len(stale_inline_images),
                settings.draft_retention_days,
            )
        except Exception:
            await db.rollback()
            logger.exception("Draft retention sweep failed")


def start_scheduler() -> None:
    """Idempotent — safe to call more than once in the same process,
    same convention as sla_scheduler.start_scheduler."""

    if scheduler.running:
        return

    interval_seconds = get_settings().draft_retention_sweep_interval_seconds

    scheduler.add_job(
        _run_draft_retention_sweep,
        trigger="interval",
        seconds=interval_seconds,
        id=DRAFT_RETENTION_JOB_ID,
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Draft retention sweep scheduler started — running every %s second(s).",
        interval_seconds,
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Draft retention sweep scheduler stopped.")

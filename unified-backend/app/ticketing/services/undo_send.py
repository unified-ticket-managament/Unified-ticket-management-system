# undo_send.py
#
# A real, server-enforced "Undo Send" window for outbound mail
# (Compose and both Reply paths — ticket-level and pre-ticket — all
# funnel through this same module, since they all already funnel
# through InteractionService._dispatch_and_record for the actual send;
# see that method's own docstring). The delay and the ability to
# cancel are both enforced here, in the backend, never trusted to a
# frontend countdown timer alone.
#
# Mirrors app.notifications.email_notifier's own established pattern
# for "run something after the request returns, without blocking it,
# safely surviving the request-scoped DB session's teardown": a
# fire-and-forget asyncio.create_task, a module-level strong-reference
# set (asyncio.create_task's Task is only weakly reachable otherwise
# and can be garbage-collected mid-flight), and the task's own,
# separately-opened AsyncSessionLocal() session — the caller's
# request-scoped session is already gone by the time this runs.
#
# No new background-job infrastructure (Celery/RQ/a second APScheduler
# job) was introduced for this — this codebase already has exactly one
# proven "delay without blocking" primitive (email_notifier.py's), and
# this reuses it verbatim rather than inventing a second one.

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.database.session import AsyncSessionLocal
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.payloads import OutboundEnvelope

logger = logging.getLogger(__name__)

# The one place this window is defined — both the backend's own
# deadline check and the frontend's countdown display derive from
# this same 10 seconds; the frontend timer is presentation only, this
# value is what's actually enforced.
UNDO_SEND_WINDOW_SECONDS = 10

_background_tasks: set[asyncio.Task] = set()


def compute_send_after() -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=UNDO_SEND_WINDOW_SECONDS)


def schedule_delayed_send(interaction_id: UUID, envelope: OutboundEnvelope) -> None:
    """
    Fire-and-forget entry point called right after an interaction has
    been committed with dispatch_status="PENDING_SEND" — schedules the
    real send for UNDO_SEND_WINDOW_SECONDS later, unless canceled
    first via InteractionService.cancel_pending_send.
    """

    task = asyncio.create_task(_send_after_delay(interaction_id, envelope))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _send_after_delay(interaction_id: UUID, envelope: OutboundEnvelope) -> None:
    await asyncio.sleep(UNDO_SEND_WINDOW_SECONDS)
    await _dispatch_if_still_pending(interaction_id, envelope)


async def _dispatch_if_still_pending(interaction_id: UUID, envelope: OutboundEnvelope) -> None:
    """
    The real, awaitable dispatch logic — kept separate from
    schedule_delayed_send's fire-and-forget wrapper so tests can await
    it directly and deterministically instead of racing a background
    task, same convention as email_notifier.dispatch_notification_emails.

    Opens its own session (the request that created this interaction
    is long gone by the time this runs) and re-fetches the interaction
    fresh — never trusts an in-memory copy — so a cancellation that
    landed after this task was scheduled but before it woke up is
    always seen. Never raises: a delivery failure is recorded on the
    interaction itself (via the same _dispatch_and_record every
    synchronous send already used), not surfaced anywhere the
    long-gone original request could see it.
    """

    # Deferred import: InteractionService imports quite a lot of this
    # package; importing it at module load time here would risk a
    # circular import, since interaction_service.py is what calls
    # schedule_delayed_send in the first place.
    from app.ticketing.services.interaction_service import InteractionService

    async with AsyncSessionLocal() as session:
        interaction_repository = InteractionRepository(session)
        interaction = await interaction_repository.get_by_id(interaction_id)

        if interaction is None:
            logger.warning("Undo-send: interaction %s no longer exists.", interaction_id)
            return

        if interaction.payload.get("dispatch_status") != "PENDING_SEND":
            # Canceled via cancel_pending_send, or (should never
            # happen) already dispatched by some other path — either
            # way, never send twice and never override a real
            # cancellation.
            return

        service = InteractionService(
            interaction_repository=interaction_repository,
            ticket_repository=TicketRepository(session),
            user_repository=UserRepository(session),
        )

        try:
            await service._dispatch_and_record(interaction, envelope)
            await session.commit()
        except Exception:
            # _dispatch_and_record's own FAILED branch already commits
            # its own error state before raising — this is a genuinely
            # unexpected second-order failure (e.g. the commit above
            # itself failing), logged rather than raised, since
            # there's no caller left to see it raised anyway.
            logger.exception(
                "Undo-send: unexpected error finalizing interaction %s.", interaction_id
            )

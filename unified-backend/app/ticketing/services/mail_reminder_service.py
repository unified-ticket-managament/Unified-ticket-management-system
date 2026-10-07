import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService, NotificationType
from app.ticketing.models.mail_reminder import MailReminder, MailReminderStatus
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_reminder_repository import (
    ActiveReminderExists,
    MailReminderRepository,
)
from app.ticketing.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

# A reminder further out than this is almost certainly a typo (wrong
# year); it also bounds how long a row can sit ACTIVE.
MAX_REMINDER_HORIZON = timedelta(days=365)

# Past this much lateness the notification says the reminder was due
# earlier (app was down / scheduler delayed) instead of reading as fresh.
OVERDUE_NOTE_AFTER = timedelta(minutes=10)

# Safety valve: at most this many reminders are handled per sweep tick;
# the remainder is picked up on the next tick.
MAX_HANDLED_PER_TICK = 200

EnsureCanView = Callable[[UUID, User], Awaitable[None]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _not_found() -> HTTPException:
    # Deliberately identical for "doesn't exist" and "belongs to someone
    # else" so reminder ids can't be probed.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Reminder not found."
    )


class MailReminderService:
    def __init__(
        self,
        reminder_repository: MailReminderRepository,
        interaction_repository: InteractionRepository,
        ensure_can_view: EnsureCanView,
    ):
        self.reminder_repository = reminder_repository
        self.interaction_repository = interaction_repository
        # Same access rule as opening the thread (see
        # build_mail_reminder_service) — injected so this service never
        # grows a weaker access path of its own.
        self.ensure_can_view = ensure_can_view

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_remind_at(value: datetime, now: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise HTTPException(
                status_code=422,
                detail="remind_at must include a timezone offset.",
            )
        value = value.astimezone(timezone.utc)
        if value <= now:
            raise HTTPException(
                status_code=422,
                detail="remind_at must be in the future.",
            )
        if value > now + MAX_REMINDER_HORIZON:
            raise HTTPException(
                status_code=422,
                detail="remind_at is too far in the future (max 1 year).",
            )
        return value

    @staticmethod
    def _duplicate() -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active reminder already exists for this email.",
        )

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------

    async def create(
        self,
        current_user: User,
        interaction_id: UUID,
        remind_at: datetime,
        *,
        now: datetime | None = None,
    ) -> MailReminder:
        now = now or _utcnow()

        interaction = await self.interaction_repository.get_by_id(interaction_id)
        if interaction is None:
            raise HTTPException(status_code=404, detail="Email not found.")

        # Replies resolve up to the thread root — the unit reminders (and
        # read/flag/pin state) are keyed on.
        if interaction.parent_interaction_id is not None:
            root = await self.interaction_repository.find_thread_root(interaction_id)
            if root is not None:
                interaction = root

        # Trash is "gone" from the user's point of view.
        if interaction.is_visible is False:
            raise HTTPException(status_code=404, detail="Email not found.")

        root_id = interaction.interaction_id

        # Same view rule as opening the email. An inaccessible email is
        # reported as 404 so its existence isn't confirmed to a user who
        # can't see it.
        try:
            await self.ensure_can_view(root_id, current_user)
        except HTTPException as exc:
            if exc.status_code in (
                status.HTTP_403_FORBIDDEN,
                status.HTTP_404_NOT_FOUND,
            ):
                raise HTTPException(
                    status_code=404, detail="Email not found."
                ) from exc
            raise

        remind_at = self.normalize_remind_at(remind_at, now)

        reminder = MailReminder(
            user_id=current_user.user_id,
            interaction_id=root_id,
            remind_at=remind_at,
            status=MailReminderStatus.ACTIVE,
            snooze_count=0,
        )
        try:
            return await self.reminder_repository.add(reminder)
        except ActiveReminderExists:
            raise self._duplicate()

    async def get(self, current_user: User, reminder_id: UUID) -> MailReminder:
        reminder = await self.reminder_repository.get_for_user(
            reminder_id, current_user.user_id
        )
        if reminder is None:
            raise _not_found()
        return reminder

    async def list_reminders(
        self,
        current_user: User,
        *,
        status_filter: str | None = None,
        interaction_id: UUID | None = None,
    ) -> list[MailReminder]:
        if status_filter is not None and status_filter not in MailReminderStatus.ALL:
            raise HTTPException(status_code=422, detail="Invalid status filter.")
        return await self.reminder_repository.list_for_user(
            current_user.user_id,
            status=status_filter,
            interaction_id=interaction_id,
        )

    async def update(
        self,
        current_user: User,
        reminder_id: UUID,
        remind_at: datetime,
        *,
        now: datetime | None = None,
    ) -> MailReminder:
        now = now or _utcnow()
        reminder = await self.get(current_user, reminder_id)
        if reminder.status != MailReminderStatus.ACTIVE:
            raise HTTPException(
                status_code=409, detail="Only an active reminder can be edited."
            )
        reminder.remind_at = self.normalize_remind_at(remind_at, now)
        return await self.reminder_repository.save(reminder)

    async def cancel(
        self, current_user: User, reminder_id: UUID, *, now: datetime | None = None
    ) -> MailReminder:
        now = now or _utcnow()
        reminder = await self.get(current_user, reminder_id)
        if reminder.status not in (
            MailReminderStatus.ACTIVE,
            MailReminderStatus.FIRED,
        ):
            raise HTTPException(
                status_code=409, detail="This reminder is already closed."
            )
        reminder.status = MailReminderStatus.CANCELED
        reminder.completed_at = now
        return await self.reminder_repository.save(reminder)

    async def snooze(
        self,
        current_user: User,
        reminder_id: UUID,
        *,
        remind_at: datetime | None = None,
        minutes: int | None = None,
        now: datetime | None = None,
    ) -> MailReminder:
        now = now or _utcnow()
        reminder = await self.get(current_user, reminder_id)
        if reminder.status not in (
            MailReminderStatus.ACTIVE,
            MailReminderStatus.FIRED,
        ):
            raise HTTPException(
                status_code=409, detail="This reminder can no longer be snoozed."
            )
        if (remind_at is None) == (minutes is None):
            raise HTTPException(
                status_code=422, detail="Provide exactly one of remind_at or minutes."
            )
        target = (
            remind_at if remind_at is not None else now + timedelta(minutes=minutes)
        )
        reminder.remind_at = self.normalize_remind_at(target, now)
        reminder.status = MailReminderStatus.ACTIVE
        reminder.snooze_count = (reminder.snooze_count or 0) + 1
        reminder.fired_at = None
        reminder.completed_at = None
        try:
            return await self.reminder_repository.save(reminder)
        except ActiveReminderExists:
            raise self._duplicate()

    async def dismiss(
        self, current_user: User, reminder_id: UUID, *, now: datetime | None = None
    ) -> MailReminder:
        now = now or _utcnow()
        reminder = await self.get(current_user, reminder_id)
        if reminder.status != MailReminderStatus.FIRED:
            raise HTTPException(
                status_code=409, detail="Only a fired reminder can be dismissed."
            )
        reminder.status = MailReminderStatus.DISMISSED
        reminder.completed_at = now
        return await self.reminder_repository.save(reminder)


def build_mail_reminder_service(db: AsyncSession) -> MailReminderService:
    async def ensure_can_view(interaction_id: UUID, current_user: User) -> None:
        # Built lazily: only "create" needs the access check, and the
        # bulk-action module pulls in most of the mail service graph —
        # get/list/patch/snooze/... should not pay for constructing it.
        from app.ticketing.services.bulk_mail_action_service import (
            build_bulk_mail_action_service,
        )

        # BulkMailActionService._ensure_can_view is the existing,
        # documented mirror of OpenEmailService's access rule (ticketed:
        # ticket view + Account Manager ownership; pending: ownership /
        # visibility tier, delegated / forwarded / shared-folder access).
        # Reusing it keeps one source of truth instead of a second,
        # possibly weaker, copy.
        await build_bulk_mail_action_service(db)._ensure_can_view(
            interaction_id, current_user
        )

    return MailReminderService(
        MailReminderRepository(db),
        InteractionRepository(db),
        ensure_can_view=ensure_can_view,
    )


# ----------------------------------------------------------------------
# Due-reminder processing (called by core/mail_reminder_scheduler.py)
# ----------------------------------------------------------------------


def _reminder_message(
    subject: str | None, reminder: MailReminder, now: datetime
) -> str:
    text = f"Reminder: {(subject or '').strip() or '(no subject)'}"
    if now - reminder.remind_at > OVERDUE_NOTE_AFTER:
        text += " (this reminder was due earlier)"
    return text


async def process_one_due_reminder(
    db: AsyncSession,
    now: datetime,
    *,
    exclude_ids: set[UUID] | None = None,
    claimed_out: list[UUID] | None = None,
    notification_service: NotificationService | None = None,
) -> UUID | None:
    """
    Claims, notifies and marks FIRED a single due reminder inside the
    caller's transaction. Returns the reminder id handled, or None when
    nothing is due. The caller commits (one reminder per transaction):
    the notification row and the ACTIVE->FIRED transition therefore
    land together or not at all, and the row lock taken by the claim is
    held until that commit so no other process can fire it too.

    `claimed_out`, if given, receives the claimed id immediately after
    the claim so the caller knows which row to skip if a later step
    raises.
    """

    repo = MailReminderRepository(db)
    reminder = await repo.claim_next_due(now, exclude_ids=exclude_ids)
    if reminder is None:
        return None
    if claimed_out is not None:
        claimed_out.append(reminder.reminder_id)

    interaction = await InteractionRepository(db).get_by_id(reminder.interaction_id)
    user = await UserRepository(db).get_by_id(reminder.user_id)

    # Nobody to remind / nothing to open: close it quietly instead of
    # re-claiming it forever or notifying about an email that's gone.
    if (
        interaction is None
        or interaction.is_visible is False
        or user is None
        or not user.is_active
    ):
        reminder.status = MailReminderStatus.CANCELED
        reminder.completed_at = now
        await db.flush()
        return reminder.reminder_id

    service = notification_service or NotificationService(NotificationRepository(db))
    root_id = reminder.interaction_id
    await service.notify(
        reminder.user_id,
        NotificationType.MAIL_REMINDER_DUE,
        "Mail Reminder",
        _reminder_message(interaction.subject, reminder, now),
        link=f"/inbox?interaction_id={root_id}",
        related_entity_type="interaction",
        related_entity_id=root_id,
    )

    reminder.status = MailReminderStatus.FIRED
    reminder.fired_at = now
    await db.flush()
    return reminder.reminder_id


async def run_due_reminders_sweep(
    session_factory,
    now: datetime | None = None,
    *,
    notification_service_factory=None,
) -> int:
    """
    One scheduler tick. Each due reminder gets its own session and
    transaction. If processing one raises, only that transaction rolls
    back (the reminder stays ACTIVE and is retried next tick); it is
    excluded for the rest of this tick so one poison row can't spin the
    loop. Returns how many reminders were handled (fired or closed).

    `notification_service_factory(db)` exists only so tests can inject a
    failing/recording notifier.
    """

    handled = 0
    failed: set[UUID] = set()

    for _ in range(MAX_HANDLED_PER_TICK):
        tick_now = now or _utcnow()
        claimed: list[UUID] = []
        async with session_factory() as db:
            try:
                reminder_id = await process_one_due_reminder(
                    db,
                    tick_now,
                    exclude_ids=failed,
                    claimed_out=claimed,
                    notification_service=(
                        notification_service_factory(db)
                        if notification_service_factory
                        else None
                    ),
                )
                if reminder_id is None:
                    await db.rollback()
                    break
                await db.commit()
                handled += 1
            except Exception:
                await db.rollback()
                logger.exception(
                    "Mail reminder processing failed; it stays ACTIVE and "
                    "will be retried on the next tick"
                )
                if not claimed:
                    # The claim itself failed (e.g. DB unavailable) — stop
                    # the tick rather than spin on a broken connection.
                    break
                failed.add(claimed[0])

    return handled

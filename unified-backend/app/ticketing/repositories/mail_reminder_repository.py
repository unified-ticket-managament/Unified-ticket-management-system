from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.mail_reminder import MailReminder, MailReminderStatus


class ActiveReminderExists(Exception):
    """The partial unique index (one ACTIVE reminder per user+thread) fired."""


class MailReminderRepository:
    """
    Per-user reminders on a mail thread root. See MailReminder.

    Never commits — callers (get_db, or the sweep's own session) own
    the transaction, same convention as every other repository here.
    Every read a *user* can reach is filtered by user_id, so ownership
    is enforced in the query itself, not left to the caller.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(self, reminder: MailReminder) -> MailReminder:
        """
        Inserts inside a SAVEPOINT so losing the one-ACTIVE-per-thread
        race (two tabs, double click) surfaces as ActiveReminderExists
        without poisoning the caller's outer transaction.
        """

        try:
            async with self.db.begin_nested():
                self.db.add(reminder)
                await self.db.flush()
        except IntegrityError as exc:
            raise ActiveReminderExists() from exc
        return reminder

    async def save(self, reminder: MailReminder) -> MailReminder:
        """Flushes changes to an already-loaded row (same SAVEPOINT guard)."""

        try:
            async with self.db.begin_nested():
                await self.db.flush()
        except IntegrityError as exc:
            raise ActiveReminderExists() from exc
        return reminder

    async def get_for_user(
        self, reminder_id: UUID, user_id: UUID
    ) -> MailReminder | None:
        result = await self.db.execute(
            select(MailReminder).where(
                MailReminder.reminder_id == reminder_id,
                MailReminder.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        status: str | None = None,
        interaction_id: UUID | None = None,
        limit: int = 500,
    ) -> list[MailReminder]:
        stmt = select(MailReminder).where(MailReminder.user_id == user_id)
        if status is not None:
            stmt = stmt.where(MailReminder.status == status)
        if interaction_id is not None:
            stmt = stmt.where(MailReminder.interaction_id == interaction_id)
        stmt = stmt.order_by(
            MailReminder.remind_at.asc(), MailReminder.reminder_id.asc()
        ).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def claim_next_due(
        self, now: datetime, *, exclude_ids: set[UUID] | None = None
    ) -> MailReminder | None:
        """
        Locks ONE ACTIVE reminder whose remind_at <= now. FOR UPDATE
        SKIP LOCKED means a second scheduler process running the same
        query simultaneously skips rows this transaction holds instead
        of blocking on (or double-processing) them. The lock lasts
        until the caller commits/rolls back, which is what ties the
        notification insert and the ACTIVE->FIRED transition together.

        Overdue rows (remind_at far in the past — e.g. the app was
        down) match too, so nothing is lost across a restart; oldest
        first.
        """

        stmt = select(MailReminder).where(
            MailReminder.status == MailReminderStatus.ACTIVE,
            MailReminder.remind_at <= now,
        )
        if exclude_ids:
            stmt = stmt.where(MailReminder.reminder_id.notin_(exclude_ids))
        stmt = (
            stmt.order_by(MailReminder.remind_at.asc(), MailReminder.reminder_id.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

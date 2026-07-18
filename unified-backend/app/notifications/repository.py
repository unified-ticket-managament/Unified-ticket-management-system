from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import Notification


class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_many(self, rows: list[dict]) -> None:
        if not rows:
            return
        self.db.add_all([Notification(**row) for row in rows])
        await self.db.flush()

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        unread_only: bool = False,
        notification_types: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Notification]:
        query = select(Notification).where(Notification.user_id == user_id)

        if unread_only:
            query = query.where(Notification.is_read.is_(False))

        if notification_types:
            query = query.where(Notification.notification_type.in_(notification_types))

        # notification_id as a tiebreaker: create_many bulk-inserts every
        # recipient of one notify() call in a single statement, and two
        # of those rows can land with an identical created_at down to
        # the microsecond — ORDER BY created_at alone doesn't guarantee
        # a stable result across repeated queries in that case, so
        # which rows fall inside/outside the LIMIT could silently
        # differ from one poll to the next.
        query = (
            query.order_by(Notification.created_at.desc(), Notification.notification_id.desc())
            .offset(offset)
            .limit(limit)
        )

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_for_user(
        self,
        user_id: UUID,
        *,
        unread_only: bool = False,
        notification_types: list[str] | None = None,
    ) -> int:
        query = select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id
        )

        if unread_only:
            query = query.where(Notification.is_read.is_(False))

        if notification_types:
            query = query.where(Notification.notification_type.in_(notification_types))

        result = await self.db.execute(query)
        return result.scalar_one()

    async def get_by_id(self, notification_id: UUID) -> Notification | None:
        result = await self.db.execute(
            select(Notification).where(Notification.notification_id == notification_id)
        )
        return result.scalar_one_or_none()

    async def mark_read(self, notification: Notification) -> Notification:
        notification.is_read = True
        await self.db.flush()
        return notification

    async def mark_all_read(self, user_id: UUID) -> None:
        await self.db.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True)
        )

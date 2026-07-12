from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.sla_breach_notification import SLABreachNotification

#sla_breach_notification_repository.py
class SLABreachNotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def try_record(
        self,
        *,
        clock_type: str,
        clock_id: UUID,
        threshold: str,
    ) -> bool:
        """
        Attempts to record that this (clock, threshold) pair has been
        notified. Returns True only if this call actually inserted the
        row — a caller should only fire the real notification in that
        case. Safe against two overlapping sweep runs racing on the
        same clock: the unique index on (clock_type, clock_id,
        threshold) means at most one of them ever sees `True`, no
        application-level lock required.
        """

        stmt = (
            insert(SLABreachNotification)
            .values(
                clock_type=clock_type,
                clock_id=clock_id,
                threshold=threshold,
            )
            .on_conflict_do_nothing(
                index_elements=["clock_type", "clock_id", "threshold"]
            )
            .returning(SLABreachNotification.sla_breach_notification_id)
        )

        result = await self.db.execute(stmt)
        inserted_id = result.scalar_one_or_none()

        await self.db.flush()

        return inserted_id is not None

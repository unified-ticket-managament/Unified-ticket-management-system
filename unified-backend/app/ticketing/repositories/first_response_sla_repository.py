from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.enums import SLAClockStatus, TicketPriority
from app.ticketing.models.first_response_sla import FirstResponseSLA

#first_response_sla_repository.py
class FirstResponseSLARepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        interaction_id: UUID,
        client_id: UUID | None,
        priority: TicketPriority,
        started_at: datetime,
        due_at: datetime,
    ) -> FirstResponseSLA:
        clock = FirstResponseSLA(
            interaction_id=interaction_id,
            client_id=client_id,
            priority=priority,
            status=SLAClockStatus.PENDING,
            started_at=started_at,
            due_at=due_at,
        )
        self.db.add(clock)
        await self.db.flush()
        await self.db.refresh(clock)
        return clock

    async def get_by_interaction_id(
        self, interaction_id: UUID
    ) -> FirstResponseSLA | None:
        result = await self.db.execute(
            select(FirstResponseSLA).where(
                FirstResponseSLA.interaction_id == interaction_id
            )
        )
        return result.scalar_one_or_none()

    async def complete(
        self,
        clock: FirstResponseSLA,
        *,
        completed_at: datetime,
        completion_reason: str,
        resulting_ticket_id: UUID | None = None,
    ) -> FirstResponseSLA | None:
        """
        No-op (returns None) if the clock isn't PENDING — SLA
        bookkeeping must never block or double-fire on the underlying
        triage action, which has already committed by the time this
        is called.
        """

        if clock.status != SLAClockStatus.PENDING:
            return None

        clock.status = SLAClockStatus.COMPLETED
        clock.completed_at = completed_at
        clock.completion_reason = completion_reason
        clock.resulting_ticket_id = resulting_ticket_id

        await self.db.flush()
        await self.db.refresh(clock)
        return clock

    async def list_active_for_sweep(self) -> list[FirstResponseSLA]:
        """
        Every still-PENDING clock — the sweep's candidate set for
        AT_RISK/BREACHED/ESCALATED classification. Not bounded by
        due_at (unlike a "give me only what's already overdue" query)
        because AT_RISK fires *before* due_at is reached — the status
        filter alone (backed by the (status, due_at) index) already
        keeps this cheap, since completed clocks are excluded.
        """

        result = await self.db.execute(
            select(FirstResponseSLA).where(
                FirstResponseSLA.status == SLAClockStatus.PENDING,
            )
        )
        return list(result.scalars().all())

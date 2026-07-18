from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.enums import SLAClockStatus
from app.ticketing.models.escalation_handling_sla import EscalationHandlingSLA

#escalation_handling_sla_repository.py

class EscalationHandlingSlaRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_by_escalation_id(
        self, escalation_id: UUID
    ) -> EscalationHandlingSLA | None:
        """
        The one currently-open (not yet breached or completed) handling
        clock for an escalation, if any — enforced at-most-one by the
        model's own partial unique index
        (ix_escalation_handling_slas_one_active_per_escalation), so
        scalar_one_or_none() is safe here. This is the idempotency check
        start_if_not_started uses: a hit means "acceptance already
        started a clock that's still running," a miss means either
        "never started" or "the previous one already breached and
        moved on" — both cases where a fresh row should be created.
        """

        result = await self.db.execute(
            select(EscalationHandlingSLA).where(
                EscalationHandlingSLA.escalation_id == escalation_id,
                EscalationHandlingSLA.breached_at.is_(None),
                EscalationHandlingSLA.completed_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_by_escalation_id(
        self, escalation_id: UUID
    ) -> EscalationHandlingSLA | None:
        """
        The most recently started handling clock for an escalation,
        active or historical — for display (the ticket detail page's
        Escalation Handling SLA card) and the "has acceptance ever
        completed" freeze check in access_control.py, neither of which
        cares whether the latest row happens to already be breached.
        """

        result = await self.db.execute(
            select(EscalationHandlingSLA)
            .where(EscalationHandlingSLA.escalation_id == escalation_id)
            .order_by(EscalationHandlingSLA.started_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def list_by_escalation_id(
        self, escalation_id: UUID
    ) -> list[EscalationHandlingSLA]:
        """Every handling clock ever started for an escalation, oldest first — history included."""

        result = await self.db.execute(
            select(EscalationHandlingSLA)
            .where(EscalationHandlingSLA.escalation_id == escalation_id)
            .order_by(EscalationHandlingSLA.started_at.asc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        escalation_id: UUID,
        ticket_id: UUID,
        target_seconds: int,
        started_at: datetime,
        due_at: datetime,
    ) -> EscalationHandlingSLA:
        clock = EscalationHandlingSLA(
            escalation_id=escalation_id,
            ticket_id=ticket_id,
            status=SLAClockStatus.RUNNING,
            target_seconds=target_seconds,
            started_at=started_at,
            due_at=due_at,
        )
        self.db.add(clock)
        await self.db.flush()
        await self.db.refresh(clock)
        return clock

    async def complete(
        self,
        clock: EscalationHandlingSLA,
        *,
        at: datetime,
    ) -> EscalationHandlingSLA | None:
        """No-op (returns None) if already COMPLETED — safe to call more than once."""

        if clock.status == SLAClockStatus.COMPLETED:
            return None

        clock.status = SLAClockStatus.COMPLETED
        clock.completed_at = at

        await self.db.flush()
        await self.db.refresh(clock)
        return clock

    async def list_newly_breached(self, *, now: datetime) -> list[EscalationHandlingSLA]:
        """
        Every RUNNING clock whose due_at has passed and hasn't already
        been marked breached — `breached_at IS NULL` is what makes
        this idempotent across sweep ticks: a clock only ever appears
        in this list once, on the first tick that observes it overdue,
        since the caller stamps breached_at immediately (see
        EscalationHandlingSlaService.evaluate_breaches).
        """

        result = await self.db.execute(
            select(EscalationHandlingSLA).where(
                EscalationHandlingSLA.status == SLAClockStatus.RUNNING,
                EscalationHandlingSLA.breached_at.is_(None),
                EscalationHandlingSLA.due_at < now,
            )
        )
        return list(result.scalars().all())

    async def mark_breached(
        self,
        clock: EscalationHandlingSLA,
        *,
        at: datetime,
    ) -> EscalationHandlingSLA | None:
        """No-op (returns None) if breached_at is already set."""

        if clock.breached_at is not None:
            return None

        clock.breached_at = at

        await self.db.flush()
        await self.db.refresh(clock)
        return clock

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.enums import EscalationLevel, EscalationStatus, TicketPriority
from app.ticketing.models.ticket_escalation import TicketEscalation

#ticket_escalation_repository.py

class TicketEscalationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_by_ticket_id(self, ticket_id: UUID) -> TicketEscalation | None:
        """
        The one non-CLOSED escalation for a ticket, if any — enforced
        at-most-one by the partial unique index on the table itself
        (see the migration), so `scalar_one_or_none` is safe here.
        """

        result = await self.db.execute(
            select(TicketEscalation).where(
                TicketEscalation.ticket_id == ticket_id,
                TicketEscalation.status != EscalationStatus.CLOSED,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, escalation_id: UUID) -> TicketEscalation | None:
        result = await self.db.execute(
            select(TicketEscalation).where(TicketEscalation.escalation_id == escalation_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        ticket_id: UUID,
        resolution_sla_id: UUID | None,
        level: EscalationLevel,
        owner_ids: set[UUID],
        triggered_by: str,
        triggered_by_user_id: UUID | None,
        ack_due_at: datetime,
        now: datetime,
        original_priority: TicketPriority,
    ) -> TicketEscalation:
        escalation = TicketEscalation(
            ticket_id=ticket_id,
            resolution_sla_id=resolution_sla_id,
            level=level,
            status=EscalationStatus.ACTIVE,
            owner_ids=[str(uid) for uid in owner_ids],
            triggered_by=triggered_by,
            triggered_by_user_id=triggered_by_user_id,
            created_at=now,
            level_started_at=now,
            ack_due_at=ack_due_at,
            original_priority=original_priority,
        )
        self.db.add(escalation)
        await self.db.flush()
        await self.db.refresh(escalation)
        return escalation

    async def advance(
        self,
        escalation: TicketEscalation,
        *,
        new_level: EscalationLevel,
        owner_ids: set[UUID],
        ack_due_at: datetime,
        now: datetime,
    ) -> TicketEscalation:
        """
        Moves to a new level (or re-notifies the same terminal SITE_LEAD
        level with a fresh ack window) — resets acknowledgment state,
        since the new owner(s) haven't acknowledged anything yet.
        Advancing at all — regardless of which level it lands on — means
        the escalation's original owner didn't act in time, so this
        always marks has_advanced_past_starting_level True; see that
        column's own docstring for why this is the acceptance-time
        Resolution SLA reshift's gate.
        """

        escalation.level = new_level
        escalation.status = EscalationStatus.ACTIVE
        escalation.owner_ids = [str(uid) for uid in owner_ids]
        escalation.level_started_at = now
        escalation.ack_due_at = ack_due_at
        escalation.acknowledged_at = None
        escalation.acknowledged_by = None
        escalation.has_advanced_past_starting_level = True

        await self.db.flush()
        await self.db.refresh(escalation)
        return escalation

    async def list_active_by_ticket_ids(
        self, ticket_ids: list[UUID]
    ) -> dict[UUID, TicketEscalation]:
        """
        Bulk form of get_active_by_ticket_id — one query for every
        ticket in a sweep batch, mirroring the sweep's other batch
        prefetches (tickets_by_id/res_clients_by_id/agents_by_id in
        SLASweepService.run_sweep) instead of a per-ticket round trip.
        """

        if not ticket_ids:
            return {}

        result = await self.db.execute(
            select(TicketEscalation).where(
                TicketEscalation.ticket_id.in_(ticket_ids),
                TicketEscalation.status != EscalationStatus.CLOSED,
            )
        )
        return {row.ticket_id: row for row in result.scalars().all()}

    async def acknowledge(
        self,
        escalation: TicketEscalation,
        *,
        acknowledged_by: UUID,
        at: datetime,
    ) -> TicketEscalation | None:
        """No-op (returns None) if not currently ACTIVE — already acknowledged or closed."""

        if escalation.status != EscalationStatus.ACTIVE:
            return None

        escalation.status = EscalationStatus.ACKNOWLEDGED
        escalation.acknowledged_at = at
        escalation.acknowledged_by = acknowledged_by

        await self.db.flush()
        await self.db.refresh(escalation)
        return escalation

    async def close(
        self,
        escalation: TicketEscalation,
        *,
        reason: str,
        at: datetime,
    ) -> TicketEscalation | None:
        """No-op (returns None) if already CLOSED."""

        if escalation.status == EscalationStatus.CLOSED:
            return None

        escalation.status = EscalationStatus.CLOSED
        escalation.closed_at = at
        escalation.closed_reason = reason

        await self.db.flush()
        await self.db.refresh(escalation)
        return escalation

    async def list_overdue_active(self, *, now: datetime) -> list[TicketEscalation]:
        """
        Every ACTIVE (not yet acknowledged) escalation whose ack_due_at
        has passed — the sweep's candidate set for auto-advance. Uses
        the same composite (status, ack_due_at) index the model
        declares, mirroring ResolutionSLARepository.list_active_for_sweep's
        own indexed-range-query shape.
        """

        result = await self.db.execute(
            select(TicketEscalation).where(
                TicketEscalation.status == EscalationStatus.ACTIVE,
                TicketEscalation.ack_due_at < now,
            )
        )
        return list(result.scalars().all())

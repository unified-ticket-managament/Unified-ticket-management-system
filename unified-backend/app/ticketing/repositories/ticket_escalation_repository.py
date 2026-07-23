from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
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
    ) -> TicketEscalation | None:
        """
        Moves to a new level (or re-notifies the same terminal SITE_LEAD
        level with a fresh ack window) — resets acknowledgment state,
        since the new owner(s) haven't acknowledged anything yet.
        Advancing at all — regardless of which level it lands on — means
        the escalation's original owner didn't act in time, so this
        always marks has_advanced_past_starting_level True; see that
        column's own docstring for why this is the acceptance-time
        Resolution SLA reshift's gate.

        Guarded by a conditional UPDATE (`escalation_id = ... AND level
        = <the level the caller observed before deciding to advance>`)
        rather than a plain ORM attribute set — mirrors
        TicketRepository.claim's own race guard. This codebase's own
        CLAUDE.md documents a real risk this protects against: a local
        dev backend and the deployed Render backend can share the same
        database, each running its own in-process scheduler, so two
        overlapping evaluate_overdue() sweeps could both read the same
        overdue escalation and both try to advance it. Returns None if
        another process already advanced (or otherwise changed) this
        escalation's level since it was read — the caller should treat
        that as "nothing to do here" (skip the audit log / notification
        for this one), not retry or raise.
        """

        result = await self.db.execute(
            update(TicketEscalation)
            .where(
                TicketEscalation.escalation_id == escalation.escalation_id,
                TicketEscalation.level == escalation.level,
            )
            .values(
                level=new_level,
                status=EscalationStatus.ACTIVE,
                owner_ids=[str(uid) for uid in owner_ids],
                level_started_at=now,
                ack_due_at=ack_due_at,
                acknowledged_at=None,
                acknowledged_by=None,
                has_advanced_past_starting_level=True,
            )
        )

        if result.rowcount == 0:
            return None

        await self.db.flush()
        await self.db.refresh(escalation)
        return escalation

    async def list_active_by_ticket_ids(
        self, ticket_ids: list[UUID], *, populate_existing: bool = False
    ) -> dict[UUID, TicketEscalation]:
        """
        Bulk form of get_active_by_ticket_id — one query for every
        ticket in a sweep batch, mirroring the sweep's other batch
        prefetches (tickets_by_id/res_clients_by_id/agents_by_id in
        SLASweepService.run_sweep) instead of a per-ticket round trip.

        `populate_existing` defaults to False (the ORM's own default),
        matching every other repository in this codebase — pass True
        when the caller specifically needs a genuinely fresh read of
        rows that might already be loaded in this session's identity
        map. SLASweepService's own refresh-before-notify step needs
        this: an escalation already prefetched at the top of a sweep
        tick (e.g. accepted, advanced, or closed by a concurrent
        request mid-tick) would otherwise silently come back as the
        same stale, already-loaded row, since AsyncSessionLocal is
        configured with expire_on_commit=False (app/database/session.py)
        and a plain SELECT never overwrites an already-mapped,
        unexpired object's attributes on its own — see
        TicketRepository.get_by_id's own docstring for the same
        explanation.
        """

        if not ticket_ids:
            return {}

        stmt = select(TicketEscalation).where(
            TicketEscalation.ticket_id.in_(ticket_ids),
            TicketEscalation.status != EscalationStatus.CLOSED,
        )
        if populate_existing:
            stmt = stmt.execution_options(populate_existing=True)
        result = await self.db.execute(stmt)
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

    async def list_handling_stage_overdue(self, *, now: datetime) -> list[TicketEscalation]:
        """
        Every escalation with a currently-running handling stage
        (handling_stage_due_at non-null) whose window has elapsed — the
        sweep's candidate set for EscalationService.
        advance_for_handling_sla_breach. A stage is "currently running"
        iff handling_stage_due_at is non-null (see TicketEscalation's
        own docstring) — that field being cleared back to NULL once
        advance_for_handling_sla_breach acts on it is what keeps this
        query returning each real breach at most once, no separate
        breach-flag column needed. Deliberately independent of
        list_overdue_active above — an escalation only ever has a
        running handling stage while ACKNOWLEDGED, never ACTIVE, so
        the two candidate sets never overlap.
        """

        result = await self.db.execute(
            select(TicketEscalation).where(
                TicketEscalation.handling_stage_due_at.is_not(None),
                TicketEscalation.handling_stage_due_at < now,
            )
        )
        return list(result.scalars().all())

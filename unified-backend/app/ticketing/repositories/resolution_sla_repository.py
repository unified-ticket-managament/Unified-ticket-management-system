from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.enums import SLAClockStatus, TicketPriority
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.resolution_sla_pause_interval import (
    ResolutionSLAPauseInterval,
)

#resolution_sla_repository.py

def compute_resumed_due_at(
    due_at: datetime, paused_at: datetime, resumed_at: datetime
) -> datetime:
    """
    Pure clock-shift math, factored out of ResolutionSLARepository.resume
    so it's unit-testable without a database — see the plan doc's §0
    and §7 (test plan). due_at always shifts forward by exactly the
    wall-clock duration the ticket spent paused.
    """

    return due_at + (resumed_at - paused_at)


def compute_reshifted_due_at(
    *,
    started_at: datetime,
    total_paused_seconds: int,
    new_target_minutes: int,
    now: datetime,
) -> datetime:
    """
    Pure clock-reshift math, factored out of
    ResolutionSLARepository.reshift_due_at_for_priority_change for the
    same reason as compute_resumed_due_at above. Preserves how much
    *running* (non-paused) time has already been consumed against
    whichever priority is now current, rather than resetting the clock
    or leaving the old target's due_at in place.
    """

    time_consumed_so_far = (now - started_at).total_seconds() - total_paused_seconds
    remaining_seconds = new_target_minutes * 60 - time_consumed_so_far
    return now + timedelta(seconds=remaining_seconds)


class ResolutionSLARepository:
    """
    Owns both `resolution_slas` and its child audit ledger
    `resolution_sla_pause_intervals` — the two are always mutated
    together on pause/resume, so splitting them into two repositories
    would just force every caller to coordinate two round-trips for
    what is really one state transition.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        ticket_id: UUID,
        client_id: UUID | None,
        priority: TicketPriority,
        started_at: datetime,
        due_at: datetime,
    ) -> ResolutionSLA:
        clock = ResolutionSLA(
            ticket_id=ticket_id,
            client_id=client_id,
            priority=priority,
            status=SLAClockStatus.RUNNING,
            started_at=started_at,
            due_at=due_at,
        )
        self.db.add(clock)
        await self.db.flush()
        await self.db.refresh(clock)
        return clock

    async def get_by_ticket_id(self, ticket_id: UUID) -> ResolutionSLA | None:
        result = await self.db.execute(
            select(ResolutionSLA).where(ResolutionSLA.ticket_id == ticket_id)
        )
        return result.scalar_one_or_none()

    async def _get_open_pause_interval(
        self, resolution_sla_id: UUID
    ) -> ResolutionSLAPauseInterval | None:
        result = await self.db.execute(
            select(ResolutionSLAPauseInterval).where(
                ResolutionSLAPauseInterval.resolution_sla_id == resolution_sla_id,
                ResolutionSLAPauseInterval.resumed_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def pause(
        self,
        clock: ResolutionSLA,
        *,
        paused_at: datetime,
        reason: str,
        triggering_interaction_id: UUID | None = None,
    ) -> ResolutionSLA | None:
        """
        No-op (returns None) if the clock isn't currently RUNNING —
        pausing an already-paused or already-completed clock must
        never double-open a pause interval or move due_at.
        """

        if clock.status != SLAClockStatus.RUNNING:
            return None

        clock.status = SLAClockStatus.PAUSED
        clock.paused_at = paused_at

        self.db.add(
            ResolutionSLAPauseInterval(
                resolution_sla_id=clock.resolution_sla_id,
                paused_at=paused_at,
                pause_reason=reason,
                triggering_interaction_id=triggering_interaction_id,
            )
        )

        await self.db.flush()
        await self.db.refresh(clock)
        return clock

    async def resume(
        self,
        clock: ResolutionSLA,
        *,
        resumed_at: datetime,
        triggering_interaction_id: UUID | None = None,
    ) -> ResolutionSLA | None:
        """
        No-op (returns None) if the clock isn't currently PAUSED.
        Shifts due_at forward by the exact pause duration (see the
        plan doc's §0 — this is what keeps the breach sweep a cheap
        indexed range query instead of a pause-history replay), closes
        the open pause interval, and adds the elapsed pause duration
        to the running total_paused_seconds display counter.
        """

        if clock.status != SLAClockStatus.PAUSED or clock.paused_at is None:
            return None

        pause_duration = resumed_at - clock.paused_at

        clock.due_at = compute_resumed_due_at(clock.due_at, clock.paused_at, resumed_at)
        clock.total_paused_seconds += int(pause_duration.total_seconds())
        clock.status = SLAClockStatus.RUNNING
        clock.paused_at = None

        open_interval = await self._get_open_pause_interval(clock.resolution_sla_id)
        if open_interval is not None:
            open_interval.resumed_at = resumed_at
            if triggering_interaction_id is not None:
                open_interval.triggering_interaction_id = triggering_interaction_id

        await self.db.flush()
        await self.db.refresh(clock)
        return clock

    async def complete(
        self,
        clock: ResolutionSLA,
        *,
        completed_at: datetime,
    ) -> ResolutionSLA | None:
        """
        No-op (returns None) if already COMPLETED. Closing directly
        from PAUSED (a manager closes a ticket that's still waiting on
        the customer) closes the open pause interval first without
        shifting due_at — the clock is ending, so due_at is moot.
        """

        if clock.status == SLAClockStatus.COMPLETED:
            return None

        if clock.status == SLAClockStatus.PAUSED:
            open_interval = await self._get_open_pause_interval(clock.resolution_sla_id)
            if open_interval is not None:
                open_interval.resumed_at = completed_at

        clock.status = SLAClockStatus.COMPLETED
        clock.completed_at = completed_at
        clock.paused_at = None

        await self.db.flush()
        await self.db.refresh(clock)
        return clock

    async def reshift_due_at_for_priority_change(
        self,
        clock: ResolutionSLA,
        *,
        new_priority: TicketPriority,
        new_target_minutes: int,
        now: datetime,
    ) -> ResolutionSLA:
        """
        Recomputes due_at against a newly-changed priority's target,
        preserving how much running (non-paused) time the clock has
        already consumed rather than either resetting the clock or
        silently leaving the old target's due_at in place. A small,
        contained exception to the "no accumulated-time model" rule in
        ResolutionSLA's own docstring — see the plan doc's §1.7.

        No-op if the clock is already COMPLETED (nothing to reshift).
        """

        if clock.status == SLAClockStatus.COMPLETED:
            return clock

        clock.priority = new_priority
        clock.due_at = compute_reshifted_due_at(
            started_at=clock.started_at,
            total_paused_seconds=clock.total_paused_seconds,
            new_target_minutes=new_target_minutes,
            now=now,
        )

        await self.db.flush()
        await self.db.refresh(clock)
        return clock

    async def list_active_for_sweep(self) -> list[ResolutionSLA]:
        """
        Every still-RUNNING clock — the sweep's candidate set for
        AT_RISK/BREACHED/ESCALATED classification. Paused clocks are
        naturally excluded by the status filter (a paused clock's
        due_at is frozen and meaningless until resume), and not
        bounded by due_at itself since AT_RISK fires before due_at is
        reached — see FirstResponseSLARepository.list_active_for_sweep's
        matching docstring.
        """

        result = await self.db.execute(
            select(ResolutionSLA).where(
                ResolutionSLA.status == SLAClockStatus.RUNNING,
            )
        )
        return list(result.scalars().all())

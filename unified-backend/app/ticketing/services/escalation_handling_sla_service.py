from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.escalation_handling_sla import EscalationHandlingSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.models.ticket_escalation import TicketEscalation
from app.ticketing.repositories.escalation_handling_sla_repository import (
    EscalationHandlingSlaRepository,
)

#escalation_handling_sla_service.py

# Fallback only — used if a caller ever passes a fraction explicitly
# (no current caller does; start_if_not_started now always passes 1.0,
# since the target it receives is already fully resolved — see that
# method's own docstring).
ESCALATION_HANDLING_SLA_FRACTION = 0.25


def compute_escalation_handling_target_seconds(
    original_target_minutes: int, fraction: float = ESCALATION_HANDLING_SLA_FRACTION
) -> int:
    """
    Pure function — `fraction` of a target-minutes value, expressed in
    seconds. `round()` (not truncation) is this codebase's existing
    duration-precision convention (whole minutes in, whole seconds
    out).
    """

    return round(original_target_minutes * 60 * fraction)


class EscalationHandlingSlaService:
    """
    Owns the internal escalation-handling clock — a second timer,
    entirely separate from ResolutionSLA, that measures how long the
    current escalation owner has to actually resolve (not just
    acknowledge) an escalated ticket once they've taken it on. See
    EscalationHandlingSLA's own model docstring for the full
    start/breach/complete lifecycle and why it's a distinct table
    rather than fields bolted onto TicketEscalation or ResolutionSLA.

    As of the handling-stage redesign (2026-07-20), this table/service
    is kept as a dual-write, not-yet-load-bearing mirror — the actual
    stage counter and reshift now live on TicketEscalation/ResolutionSLA
    (see EscalationService._complete_acceptance), and this service no
    longer independently resolves a policy/percentage: it accepts the
    already-computed target from that caller so the two writes can
    never diverge. Kept alive (not deleted) per this session's "migrate
    behavior first, verify nothing depends on it, remove in a later
    cleanup phase" decision — see the plan doc.
    """

    def __init__(
        self,
        escalation_handling_sla_repository: EscalationHandlingSlaRepository,
    ):
        self.escalation_handling_sla_repository = escalation_handling_sla_repository

    async def start_if_not_started(
        self,
        *,
        escalation: TicketEscalation,
        ticket: Ticket,
        target_minutes: int,
    ) -> EscalationHandlingSLA | None:
        """
        Idempotent against repeated acceptance at the SAME level —
        acknowledging (or assignment-treated-as-acknowledgment) more
        than once while the current clock is still open must never
        create a second row or push due_at forward again, so this
        checks for an ACTIVE (un-breached, un-completed) row, not just
        any row ever created for this escalation. If the previous
        clock already breached — the owner didn't resolve it in time,
        so the escalation advanced a level — this deliberately DOES
        create a fresh row rather than returning the breached one. The
        breached row is left untouched as history.

        `target_minutes` is the already-resolved handling-stage target
        (original_resolution_target_minutes x handling_stage_percentage
        for whichever stage is about to start) — computed once by
        EscalationService._complete_acceptance and passed in unchanged,
        rather than independently re-derived here from a policy lookup.
        This is what keeps this table's numbers identical to
        ResolutionSLA's own reshifted active_target_minutes during the
        parallel-run window.
        """

        existing_active = await self.escalation_handling_sla_repository.get_active_by_escalation_id(
            escalation.escalation_id
        )
        if existing_active is not None:
            return existing_active

        target_seconds = compute_escalation_handling_target_seconds(target_minutes, 1.0)
        started_at = datetime.now(timezone.utc)
        due_at = started_at + timedelta(seconds=target_seconds)

        return await self.escalation_handling_sla_repository.create(
            escalation_id=escalation.escalation_id,
            ticket_id=ticket.ticket_id,
            target_seconds=target_seconds,
            started_at=started_at,
            due_at=due_at,
        )

    async def complete_for_escalation(self, escalation_id: UUID) -> None:
        """
        Called when the escalation itself closes (ticket resolved, or
        any other closing path) — completes the currently-ACTIVE
        handling clock, if any (e.g. the escalation was closed before
        anyone accepted it, or the only clock that ever ran already
        breached — both leave nothing active to complete). Historical
        breached rows from an earlier level are left alone; they're
        already terminal.
        """

        clock = await self.escalation_handling_sla_repository.get_active_by_escalation_id(
            escalation_id
        )
        if clock is None:
            return

        await self.escalation_handling_sla_repository.complete(
            clock, at=datetime.now(timezone.utc)
        )

    async def evaluate_breaches(self, *, now: datetime) -> list[EscalationHandlingSLA]:
        """
        Sweep hook — every RUNNING handling clock whose due_at has just
        passed gets breached_at stamped (idempotent: only clocks with
        breached_at still NULL are candidates at all, so a clock is
        returned here at most once across every sweep tick, ever).

        As of the handling-stage redesign, the sweep still calls this
        (so this table's own breached_at/status stay accurate for
        anyone still reading it — e.g. the ticket-detail "Escalation
        Handling SLA" card) but no longer uses its return value to
        drive escalation advancement — that's now driven by
        TicketEscalation.handling_stage_due_at directly (see
        SLASweepService.run_sweep), to avoid the old and new mechanisms
        double-firing EscalationService.advance_for_handling_sla_breach
        for the same real-world breach.
        """

        overdue = await self.escalation_handling_sla_repository.list_newly_breached(now=now)
        breached: list[EscalationHandlingSLA] = []

        for clock in overdue:
            updated = await self.escalation_handling_sla_repository.mark_breached(
                clock, at=now
            )
            if updated is not None:
                breached.append(updated)

        return breached


def build_escalation_handling_sla_service(db: AsyncSession) -> EscalationHandlingSlaService:
    return EscalationHandlingSlaService(
        escalation_handling_sla_repository=EscalationHandlingSlaRepository(db),
    )

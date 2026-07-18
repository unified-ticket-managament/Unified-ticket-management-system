from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.enums import TicketPriority
from app.ticketing.models.escalation_handling_sla import EscalationHandlingSLA
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.sla_policy import SLAPolicy
from app.ticketing.models.ticket import Ticket
from app.ticketing.models.ticket_escalation import TicketEscalation
from app.ticketing.repositories.escalation_handling_sla_repository import (
    EscalationHandlingSlaRepository,
)
from app.ticketing.repositories.resolution_sla_repository import ResolutionSLARepository
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository

#escalation_handling_sla_service.py

# Fallback only — used if a policy row somehow has no
# handling_sla_percentage (shouldn't happen once the column's own
# NOT NULL + default are in place, but kept as a safe default rather
# than a crash). The real, per-priority value now lives on
# SLAPolicy.handling_sla_percentage (see the admin-facing SLA Timing
# Matrix), not a single global fraction.
ESCALATION_HANDLING_SLA_FRACTION = 0.25


def compute_escalation_handling_target_seconds(
    original_target_minutes: int, fraction: float = ESCALATION_HANDLING_SLA_FRACTION
) -> int:
    """
    Pure function — `fraction` of the original (configured) Resolution
    SLA target, expressed in seconds. `round()` (not truncation) is
    this codebase's existing duration-precision convention (whole
    minutes in, whole seconds out) — for this app's actual policy
    values (HIGH=4320min, MEDIUM=7200min, LOW=10080min) at the default
    25% every result is already an exact whole number of seconds, but
    `round()` keeps this well-defined for any configured fraction.
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
    """

    def __init__(
        self,
        escalation_handling_sla_repository: EscalationHandlingSlaRepository,
        resolution_sla_repository: ResolutionSLARepository,
        sla_policy_repository: SLAPolicyRepository,
    ):
        self.escalation_handling_sla_repository = escalation_handling_sla_repository
        self.resolution_sla_repository = resolution_sla_repository
        self.sla_policy_repository = sla_policy_repository

    async def _resolve_policy(
        self,
        *,
        ticket: Ticket,
    ) -> SLAPolicy | None:
        """
        Resolves the SLA policy whose `resolution_target_minutes` (and,
        as of this method's rename, `handling_sla_percentage`) apply to
        this ticket — from the priority ResolutionSLA snapshotted at
        ticket-creation time when that clock still exists (the common
        case; a ticket has at most one ResolutionSLA row, ever, so
        looking it up by ticket_id always returns the same row
        `escalation.resolution_sla_id` denormalizes), falling back to
        the ticket's current priority only if the ticket somehow never
        had a Resolution clock at all (see ResolutionSLARepository/
        SLAService for when that can happen). The resolution target
        itself is never derived from remaining/overdue time — only
        ever the configured target.
        """

        resolution_clock = await self.resolution_sla_repository.get_by_ticket_id(
            ticket.ticket_id
        )
        priority: TicketPriority = (
            resolution_clock.priority if resolution_clock is not None else ticket.current_priority
        )

        return await self.sla_policy_repository.get_by_priority(priority)

    async def start_if_not_started(
        self,
        *,
        escalation: TicketEscalation,
        ticket: Ticket,
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
        create a fresh row rather than returning the breached one: the
        new acceptance is happening at a new level, generally after
        _reshift_sla_for_escalation_acceptance has already moved the
        Resolution SLA clock onto CRITICAL's target, so _resolve_policy
        (which reads that same clock's priority) now correctly resolves
        CRITICAL's handling percentage instead of the original
        priority's. The breached row is left untouched as history.
        Returns None (skips creation) if no SLA policy can be resolved
        for this ticket's priority — the same "never let missing SLA
        config block the underlying action" convention SLAService
        itself uses.
        """

        existing_active = await self.escalation_handling_sla_repository.get_active_by_escalation_id(
            escalation.escalation_id
        )
        if existing_active is not None:
            return existing_active

        policy = await self._resolve_policy(ticket=ticket)
        if policy is None:
            return None

        target_seconds = compute_escalation_handling_target_seconds(
            policy.resolution_target_minutes, policy.handling_sla_percentage / 100
        )
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
        Returns the freshly-breached rows so the caller (SLASweepService)
        can notify the current escalation owner and advance the
        escalation level for each one.
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
        resolution_sla_repository=ResolutionSLARepository(db),
        sla_policy_repository=SLAPolicyRepository(db),
    )

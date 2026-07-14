from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.enums import TicketPriority
from app.ticketing.models.escalation_handling_sla import EscalationHandlingSLA
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.models.ticket_escalation import TicketEscalation
from app.ticketing.repositories.escalation_handling_sla_repository import (
    EscalationHandlingSlaRepository,
)
from app.ticketing.repositories.resolution_sla_repository import ResolutionSLARepository
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository

#escalation_handling_sla_service.py

# The escalation-handling SLA's target is this fixed fraction of the
# ORIGINAL Resolution SLA's configured target duration — computed from
# the configured target, never from remaining/overdue time (see this
# module's own compute function). Not a per-policy column: every
# priority uses the same fraction today, and the one formula lives
# here, not duplicated at each call site.
ESCALATION_HANDLING_SLA_FRACTION = 0.25


def compute_escalation_handling_target_seconds(original_target_minutes: int) -> int:
    """
    Pure function — 25% of the original (configured) Resolution SLA
    target, expressed in seconds. `round()` (not truncation) is this
    codebase's existing duration-precision convention (whole minutes
    in, whole seconds out) — for this app's actual policy values
    (HIGH=4320min, MEDIUM=7200min, LOW=10080min) every result is
    already an exact whole number of seconds, but `round()` keeps this
    well-defined even if a future policy value doesn't divide evenly.
    """

    return round(original_target_minutes * 60 * ESCALATION_HANDLING_SLA_FRACTION)


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

    async def _resolve_original_target_minutes(
        self,
        *,
        ticket: Ticket,
    ) -> int | None:
        """
        "Original SLA target" means the Resolution SLA's own
        configured per-priority target — resolved from the priority
        ResolutionSLA snapshotted at ticket-creation time when that
        clock still exists (the common case; a ticket has at most one
        ResolutionSLA row, ever, so looking it up by ticket_id always
        returns the same row `escalation.resolution_sla_id` denormalizes),
        falling back to the ticket's current priority only if the
        ticket somehow never had a Resolution clock at all (see
        ResolutionSLARepository/SLAService for when that can happen).
        Never derived from remaining/overdue time — only ever the
        configured target.
        """

        resolution_clock = await self.resolution_sla_repository.get_by_ticket_id(
            ticket.ticket_id
        )
        priority: TicketPriority = (
            resolution_clock.priority if resolution_clock is not None else ticket.current_priority
        )

        policy = await self.sla_policy_repository.get_by_priority(priority)
        return policy.resolution_target_minutes if policy is not None else None

    async def start_if_not_started(
        self,
        *,
        escalation: TicketEscalation,
        ticket: Ticket,
    ) -> EscalationHandlingSLA | None:
        """
        Idempotent — the one guarantee the whole feature depends on:
        acknowledging (or assignment-treated-as-acknowledgment) more
        than once, or acknowledging after an already-started handling
        clock, must never create a second row or push due_at forward
        again. Returns the existing row unchanged if one is already
        present, only ever creating on a genuine first call. Returns
        None (skips creation) if no SLA policy can be resolved for
        this ticket's priority — the same "never let missing SLA
        config block the underlying action" convention SLAService
        itself uses.
        """

        existing = await self.escalation_handling_sla_repository.get_by_escalation_id(
            escalation.escalation_id
        )
        if existing is not None:
            return existing

        target_minutes = await self._resolve_original_target_minutes(ticket=ticket)
        if target_minutes is None:
            return None

        target_seconds = compute_escalation_handling_target_seconds(target_minutes)
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
        any other closing path) — no-op if no handling clock was ever
        started (e.g. the escalation was closed before anyone
        acknowledged it) or it's already completed.
        """

        clock = await self.escalation_handling_sla_repository.get_by_escalation_id(
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

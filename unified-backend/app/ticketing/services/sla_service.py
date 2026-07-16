import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.notifications.service import NotificationService
from app.ticketing.enums import (
    AuditEntityType,
    AuditEventType,
    InteractionDirection,
    SLAClockStatus,
    TicketPriority,
)
from app.ticketing.models.first_response_sla import FirstResponseSLA
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.sla_policy import SLAPolicy
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.escalation_handling_sla_repository import (
    EscalationHandlingSlaRepository,
)
from app.ticketing.repositories.first_response_sla_repository import (
    FirstResponseSLARepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.resolution_sla_repository import (
    ResolutionSLARepository,
)
from app.ticketing.repositories.sla_breach_notification_repository import (
    SLABreachNotificationRepository,
)
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.interaction import InteractionCreate
from app.ticketing.schemas.sla import (
    EscalationHandlingSLAState,
    FirstResponseSLAState,
    ResolutionSLAState,
    SLAPauseRequest,
    SLAPolicyResponse,
    SLAPolicyUpdate,
    TicketSLAResponse,
)
from app.ticketing.schemas.ticket_action import TicketActionResponse
from app.ticketing.services.access_control import (
    ensure_account_manager_owns_ticket_client,
    ensure_can_manage_sla_policies,
    ensure_can_override_sla,
)
from app.ticketing.services.audit_log_service import AuditLogService
from app.ticketing.services.escalation_service import build_escalation_service
from app.ticketing.services.sla_breach_notifier import (
    CLOCK_TYPE_FIRST_RESPONSE,
    notify_first_response_threshold,
    resolve_global_inbox_user_ids,
)
from app.ticketing.services.sla_escalation_rules import thresholds_reached

logger = logging.getLogger(__name__)

# Default priority used to look up a First Response policy for a
# still-pending inbox item, which has no priority field of its own —
# see FirstResponseSLA's own docstring for why this is an accepted v1
# limitation rather than a correctness bug.
DEFAULT_FIRST_RESPONSE_PRIORITY = TicketPriority.MEDIUM


def compute_elapsed_fraction(
    *, due_at: datetime, target_minutes: int, at: datetime
) -> float:
    """
    Pure fraction-of-target-consumed math, shared by the read-state
    endpoint and the breach sweep. Derived directly from `due_at` and
    the target — never touches `started_at` or pause history — which
    is the whole payoff of shifting `due_at` on every resume (see the
    plan doc's §0): 1.0 means "exactly at the target", regardless of
    how many pause/resume cycles it took to get there.
    """

    target_seconds = target_minutes * 60
    if target_seconds <= 0:
        return 1.0

    remaining_seconds = (due_at - at).total_seconds()
    return 1.0 - (remaining_seconds / target_seconds)


class SLAService:
    """
    Orchestrates both SLA clocks: creation/completion hooks called
    from EmailService/InteractionService/InboxTicketService, the
    read-state endpoint, admin policy CRUD, and the manual pause/
    resume override action. Every clock-mutating method here is
    best-effort/no-op-tolerant on the "hook" side (SLA bookkeeping
    must never block or fail the underlying business action it's
    attached to) — only the manual override and policy-CRUD methods,
    which are the SLA feature's own direct actions, raise on failure.
    """

    def __init__(
        self,
        sla_policy_repository: SLAPolicyRepository,
        first_response_sla_repository: FirstResponseSLARepository,
        resolution_sla_repository: ResolutionSLARepository,
        ticket_repository: TicketRepository | None = None,
        interaction_repository: InteractionRepository | None = None,
        notification_service: NotificationService | None = None,
        client_repository: ClientRepository | None = None,
        user_repository: UserRepository | None = None,
        sla_breach_notification_repository: SLABreachNotificationRepository | None = None,
    ):
        self.sla_policy_repository = sla_policy_repository
        self.first_response_sla_repository = first_response_sla_repository
        self.resolution_sla_repository = resolution_sla_repository
        self.ticket_repository = ticket_repository
        self.interaction_repository = interaction_repository
        self.notification_service = notification_service
        # Only needed for the completion-time breach check in
        # complete_first_response_clock (see that method) — optional,
        # like notification_service, so this stays a plain no-op for
        # any caller that hasn't been updated to pass them.
        self.client_repository = client_repository
        self.user_repository = user_repository
        self.sla_breach_notification_repository = sla_breach_notification_repository

    # ---------------------------------------------------------
    # Policy lookup
    # ---------------------------------------------------------

    async def _get_policy(self, priority: TicketPriority) -> SLAPolicy | None:
        policy = await self.sla_policy_repository.get_by_priority(priority)

        if policy is None:
            # Policies are seeded 1:1 with TicketPriority at migration
            # time — a missing one means that seed hasn't run yet.
            # Never let missing SLA config block the underlying
            # business action (sending an email, creating a ticket).
            logger.warning(
                "No active SLAPolicy found for priority %s — skipping SLA clock.",
                priority,
            )

        return policy

    # ---------------------------------------------------------
    # First Response clock
    # ---------------------------------------------------------

    async def start_first_response_clock(
        self,
        *,
        interaction: Interaction,
    ) -> FirstResponseSLA | None:
        """
        Called from EmailService.receive_email, only for a genuinely
        new thread root (never a reply threading onto an existing
        pending item or ticket) — see the plan doc's gap #7.
        """

        policy = await self._get_policy(DEFAULT_FIRST_RESPONSE_PRIORITY)
        if policy is None:
            return None

        started_at = interaction.received_at or datetime.now(timezone.utc)
        due_at = started_at + timedelta(minutes=policy.first_response_target_minutes)

        return await self.first_response_sla_repository.create(
            interaction_id=interaction.interaction_id,
            client_id=interaction.client_id,
            priority=DEFAULT_FIRST_RESPONSE_PRIORITY,
            started_at=started_at,
            due_at=due_at,
        )

    async def complete_first_response_clock(
        self,
        *,
        interaction_id: UUID,
        completion_reason: str,
        resulting_ticket_id: UUID | None = None,
    ) -> None:
        """
        Called from each of the four triage actions (archive, reply,
        attach-to-ticket, create-ticket). Silently no-ops if no clock
        exists for this interaction (predates this feature's rollout —
        see the backfill script) or it's already completed — SLA
        bookkeeping must never block triage.

        Also checks the clock against every SLA threshold *at the
        moment of completion*, before marking it COMPLETED, and fires
        any not-yet-recorded breach notification right here. This is
        not redundant with the periodic sweep: SLASweepService.
        run_sweep only ever looks at still-PENDING clocks
        (list_active_for_sweep), so a clock that breaches its target
        and then gets completed (an agent finally replies, or attaches
        it to a ticket) *before the next sweep tick* would otherwise
        never be caught — once COMPLETED, it's permanently invisible
        to the sweep, no matter how far past its target it ran. A
        First Response clock's whole lifecycle is often minutes, well
        inside a sweep interval that's only guaranteed by a
        once-a-minute cron in production and isn't running at all
        during local/manual testing — so this gap isn't hypothetical.
        Uses the same idempotency ledger (SLABreachNotificationRepository
        .try_record_many) the sweep does, so if the sweep DID already
        catch this clock first, nothing double-fires here.
        """

        clock = await self.first_response_sla_repository.get_by_interaction_id(
            interaction_id
        )
        if clock is None:
            return

        completed_at = datetime.now(timezone.utc)

        if (
            clock.status == SLAClockStatus.PENDING
            and self.sla_breach_notification_repository is not None
        ):
            policy = await self._get_policy(clock.priority)
            target_minutes = policy.first_response_target_minutes if policy is not None else 0
            fraction = compute_elapsed_fraction(
                due_at=clock.due_at, target_minutes=target_minutes, at=completed_at
            )
            reached = thresholds_reached(fraction)

            if reached:
                candidates = [
                    (CLOCK_TYPE_FIRST_RESPONSE, clock.first_response_sla_id, threshold)
                    for threshold in reached
                ]
                newly_recorded = (
                    await self.sla_breach_notification_repository.try_record_many(
                        candidates
                    )
                )

                if newly_recorded:
                    client = (
                        await self.client_repository.get_by_id(clock.client_id)
                        if clock.client_id is not None and self.client_repository is not None
                        else None
                    )
                    interaction = (
                        await self.interaction_repository.get_by_id(clock.interaction_id)
                        if self.interaction_repository is not None
                        else None
                    )
                    global_inbox_ids = (
                        await resolve_global_inbox_user_ids(self.user_repository)
                        if self.user_repository is not None
                        else set()
                    )
                    for _, _, threshold in newly_recorded:
                        await notify_first_response_threshold(
                            clock=clock,
                            threshold=threshold,
                            client=client,
                            interaction=interaction,
                            global_inbox_ids=global_inbox_ids,
                            notification_service=self.notification_service,
                            user_repository=self.user_repository,
                        )

        await self.first_response_sla_repository.complete(
            clock,
            completed_at=completed_at,
            completion_reason=completion_reason,
            resulting_ticket_id=resulting_ticket_id,
        )

    # ---------------------------------------------------------
    # Resolution clock
    # ---------------------------------------------------------

    async def start_resolution_clock(
        self,
        *,
        ticket_id: UUID,
        client_id: UUID | None,
        priority: TicketPriority,
    ) -> ResolutionSLA | None:
        """Called from InboxTicketService.create_ticket_from_interaction."""

        policy = await self._get_policy(priority)
        if policy is None:
            return None

        started_at = datetime.now(timezone.utc)
        due_at = started_at + timedelta(minutes=policy.resolution_target_minutes)

        return await self.resolution_sla_repository.create(
            ticket_id=ticket_id,
            client_id=client_id,
            priority=priority,
            started_at=started_at,
            due_at=due_at,
        )

    async def create_or_resume_resolution_clock(
        self,
        *,
        ticket_id: UUID,
        client_id: UUID | None,
        priority: TicketPriority,
    ) -> None:
        """
        Called from InboxTicketService.attach_to_existing_ticket — see
        the plan doc's §2.2 for the four sub-cases: no clock yet
        (create fresh), PAUSED (resume), RUNNING (no-op), COMPLETED
        (no-op — never resurrect a clock on a closed ticket).
        """

        clock = await self.resolution_sla_repository.get_by_ticket_id(ticket_id)

        if clock is None:
            await self.start_resolution_clock(
                ticket_id=ticket_id, client_id=client_id, priority=priority
            )
            return

        if clock.status == SLAClockStatus.PAUSED:
            await self.resolution_sla_repository.resume(
                clock, resumed_at=datetime.now(timezone.utc)
            )

        # RUNNING / COMPLETED: no-op.

    async def pause_resolution_clock(
        self,
        *,
        ticket_id: UUID,
        reason: str,
        triggering_interaction_id: UUID | None = None,
    ) -> None:
        """Called from InteractionService.change_status on entry into WAITING_FOR_CLIENT."""

        clock = await self.resolution_sla_repository.get_by_ticket_id(ticket_id)
        if clock is None:
            return

        await self.resolution_sla_repository.pause(
            clock,
            paused_at=datetime.now(timezone.utc),
            reason=reason,
            triggering_interaction_id=triggering_interaction_id,
        )

    async def resume_resolution_clock(
        self,
        *,
        ticket_id: UUID,
        triggering_interaction_id: UUID | None = None,
    ) -> None:
        """
        Called from two independent trigger points (see the plan
        doc's gap #4): InteractionService.change_status on exit from
        WAITING_FOR_CLIENT (agent-driven), and EmailService.
        receive_email's threaded-onto-existing-ticket branch
        (customer-driven, independent of whether the ticket's status
        label has been changed yet).
        """

        clock = await self.resolution_sla_repository.get_by_ticket_id(ticket_id)
        if clock is None:
            return

        await self.resolution_sla_repository.resume(
            clock,
            resumed_at=datetime.now(timezone.utc),
            triggering_interaction_id=triggering_interaction_id,
        )

    async def complete_resolution_clock(self, *, ticket_id: UUID) -> None:
        """
        Called from InteractionService.change_status on entry into
        CLOSED. Also closes any active internal escalation for this
        ticket (see EscalationService.close_for_ticket_resolution) —
        an escalation never outlives the ticket it was raised on, but
        this never touches the Resolution SLA row itself beyond the
        usual `complete()` call already below.
        """

        clock = await self.resolution_sla_repository.get_by_ticket_id(ticket_id)
        if clock is None:
            return

        await self.resolution_sla_repository.complete(
            clock, completed_at=datetime.now(timezone.utc)
        )

        if self.ticket_repository is not None:
            escalation_service = build_escalation_service(self.ticket_repository.db)
            await escalation_service.close_for_ticket_resolution(ticket_id)

    async def reshift_resolution_clock_for_priority_change(
        self,
        *,
        ticket_id: UUID,
        new_priority: TicketPriority,
    ) -> None:
        """Called from InteractionService.change_priority."""

        clock = await self.resolution_sla_repository.get_by_ticket_id(ticket_id)
        if clock is None:
            return

        policy = await self._get_policy(new_priority)
        if policy is None:
            return

        await self.resolution_sla_repository.reshift_due_at_for_priority_change(
            clock,
            new_priority=new_priority,
            new_target_minutes=policy.resolution_target_minutes,
            now=datetime.now(timezone.utc),
        )

    # ---------------------------------------------------------
    # Read state
    # ---------------------------------------------------------

    async def get_ticket_sla_state(self, *, ticket_id: UUID) -> TicketSLAResponse:
        """
        `first_response` is always None here — a ticket's First
        Response clock lives on its originating pre-ticket Interaction,
        not the Ticket row itself, so resolving it would require
        walking back to that interaction (not all callers of this
        ticket-level endpoint need it). Use
        get_first_response_sla_state(interaction_id) directly against
        the originating interaction when that's needed.
        """

        resolution_clock = await self.resolution_sla_repository.get_by_ticket_id(
            ticket_id
        )

        resolution_state = None
        if resolution_clock is not None:
            policy = await self._get_policy(resolution_clock.priority)
            target_minutes = (
                policy.resolution_target_minutes if policy is not None else 0
            )
            at = resolution_clock.completed_at or datetime.now(timezone.utc)
            resolution_state = ResolutionSLAState(
                status=resolution_clock.status,
                started_at=resolution_clock.started_at,
                due_at=resolution_clock.due_at,
                paused_at=resolution_clock.paused_at,
                total_paused_seconds=resolution_clock.total_paused_seconds,
                completed_at=resolution_clock.completed_at,
                elapsed_fraction=compute_elapsed_fraction(
                    due_at=resolution_clock.due_at,
                    target_minutes=target_minutes,
                    at=at,
                ),
            )

        escalation_state = None
        handling_sla_state = None
        if self.ticket_repository is not None:
            db = self.ticket_repository.db
            escalation_service = build_escalation_service(db)
            escalation_state = await escalation_service.get_escalation_state(ticket_id)

            if escalation_state is not None:
                handling_sla_repository = EscalationHandlingSlaRepository(db)
                handling_clock = await handling_sla_repository.get_by_escalation_id(
                    escalation_state.escalation_id
                )
                if handling_clock is not None:
                    now = datetime.now(timezone.utc)
                    at = handling_clock.completed_at or now
                    handling_sla_state = EscalationHandlingSLAState(
                        status=handling_clock.status,
                        target_seconds=handling_clock.target_seconds,
                        started_at=handling_clock.started_at,
                        due_at=handling_clock.due_at,
                        breached_at=handling_clock.breached_at,
                        completed_at=handling_clock.completed_at,
                        remaining_seconds=(handling_clock.due_at - at).total_seconds(),
                    )

        return TicketSLAResponse(
            ticket_id=ticket_id,
            first_response=None,
            resolution=resolution_state,
            escalation=escalation_state,
            escalation_handling_sla=handling_sla_state,
        )

    async def get_first_response_sla_state(
        self, *, interaction_id: UUID
    ) -> FirstResponseSLAState | None:
        clock = await self.first_response_sla_repository.get_by_interaction_id(
            interaction_id
        )
        if clock is None:
            return None

        policy = await self._get_policy(clock.priority)
        target_minutes = policy.first_response_target_minutes if policy is not None else 0
        at = clock.completed_at or datetime.now(timezone.utc)

        return FirstResponseSLAState(
            status=clock.status,
            started_at=clock.started_at,
            due_at=clock.due_at,
            completed_at=clock.completed_at,
            completion_reason=clock.completion_reason,
            elapsed_fraction=compute_elapsed_fraction(
                due_at=clock.due_at, target_minutes=target_minutes, at=at
            ),
        )

    # ---------------------------------------------------------
    # Admin policy CRUD
    # ---------------------------------------------------------

    async def list_policies(self, current_user: User) -> list[SLAPolicyResponse]:
        policies = await self.sla_policy_repository.list_all()
        return [SLAPolicyResponse.model_validate(p) for p in policies]

    async def update_policy(
        self,
        policy_id: UUID,
        request: SLAPolicyUpdate,
        current_user: User,
    ) -> SLAPolicyResponse:
        ensure_can_manage_sla_policies(current_user)

        policy = await self.sla_policy_repository.get_by_id(policy_id)
        if policy is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="SLA policy not found.",
            )

        # Cross-field validation the per-field Pydantic bounds on
        # SLAPolicyUpdate can't express on their own: Warning 1 ("Half
        # Elapsed") must fire before Warning 2 ("At Risk") as elapsed
        # time increases toward the fixed Breached (100%) threshold.
        # Computed against the EFFECTIVE final values (the incoming
        # request's value if provided, else the policy's current
        # stored one) rather than just the request in isolation — a
        # request that only touches warning_1_percentage must still be
        # rejected if it would leave the stored warning_2_percentage
        # inverted; SLAPolicyUpdate's own model_validator only catches
        # the case where both are supplied together in one request.
        effective_warning_1 = (
            request.warning_1_percentage
            if request.warning_1_percentage is not None
            else policy.warning_1_percentage
        )
        effective_warning_2 = (
            request.warning_2_percentage
            if request.warning_2_percentage is not None
            else policy.warning_2_percentage
        )
        if effective_warning_1 >= effective_warning_2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Warning 1 ({effective_warning_1:g}%) must be less than "
                    f"Warning 2 ({effective_warning_2:g}%) — Warning 1 fires "
                    "first as elapsed time increases."
                ),
            )

        updated = await self.sla_policy_repository.update(
            policy,
            first_response_target_minutes=request.first_response_target_minutes,
            resolution_target_minutes=request.resolution_target_minutes,
            escalation_ack_target_minutes=request.escalation_ack_target_minutes,
            handling_sla_percentage=request.handling_sla_percentage,
            warning_1_percentage=request.warning_1_percentage,
            warning_2_percentage=request.warning_2_percentage,
            is_active=request.is_active,
        )

        return SLAPolicyResponse.model_validate(updated)

    # ---------------------------------------------------------
    # Manual pause / resume override
    #
    # Follows this repo's add-ticket-action recipe: fetch-or-404 ->
    # access-control gate -> resolve actor -> mutate -> write an
    # Interaction -> write an AuditLog row.
    # ---------------------------------------------------------

    async def _get_ticket_or_404(self, ticket_id: UUID):
        ticket = await self.ticket_repository.get_by_id(ticket_id)
        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )
        return ticket

    async def _create_sla_interaction(
        self,
        *,
        ticket_id: UUID,
        interaction_type: str,
        payload: dict[str, Any],
        performed_by: UUID | None,
    ) -> Interaction:
        return await self.interaction_repository.create(
            InteractionCreate(
                ticket_id=ticket_id,
                interaction_type=interaction_type,
                direction=InteractionDirection.INTERNAL,
                performed_by=performed_by,
                payload=payload,
                is_visible=True,
            )
        )

    async def manual_pause(
        self,
        ticket_id: UUID,
        request: SLAPauseRequest,
        current_user: User,
    ) -> TicketActionResponse:
        ticket = await self._get_ticket_or_404(ticket_id)
        ensure_can_override_sla(current_user)
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )

        clock = await self.resolution_sla_repository.get_by_ticket_id(ticket_id)
        if clock is None or clock.status != SLAClockStatus.RUNNING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This ticket's Resolution SLA is not currently running.",
            )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        interaction = await self._create_sla_interaction(
            ticket_id=ticket_id,
            interaction_type="SLA_PAUSED",
            payload={"reason": request.reason},
            performed_by=actor_id,
        )

        await self.resolution_sla_repository.pause(
            clock,
            paused_at=datetime.now(timezone.utc),
            reason="MANUAL_OVERRIDE",
            triggering_interaction_id=interaction.interaction_id,
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.SLA_PAUSED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={
                "reason": request.reason,
                "interaction_id": interaction.interaction_id,
                "trigger": "manual_override",
            },
        )

        return TicketActionResponse(
            interaction_id=interaction.interaction_id,
            ticket_id=ticket_id,
            message="Resolution SLA paused.",
            created_at=interaction.created_at,
        )

    async def manual_resume(
        self,
        ticket_id: UUID,
        current_user: User,
    ) -> TicketActionResponse:
        ticket = await self._get_ticket_or_404(ticket_id)
        ensure_can_override_sla(current_user)
        await ensure_account_manager_owns_ticket_client(
            ticket, current_user, self.client_repository
        )

        clock = await self.resolution_sla_repository.get_by_ticket_id(ticket_id)
        if clock is None or clock.status != SLAClockStatus.PAUSED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This ticket's Resolution SLA is not currently paused.",
            )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        interaction = await self._create_sla_interaction(
            ticket_id=ticket_id,
            interaction_type="SLA_RESUMED",
            payload={},
            performed_by=actor_id,
        )

        await self.resolution_sla_repository.resume(
            clock,
            resumed_at=datetime.now(timezone.utc),
            triggering_interaction_id=interaction.interaction_id,
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.SLA_RESUMED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={
                "interaction_id": interaction.interaction_id,
                "trigger": "manual_override",
            },
        )

        return TicketActionResponse(
            interaction_id=interaction.interaction_id,
            ticket_id=ticket_id,
            message="Resolution SLA resumed.",
            created_at=interaction.created_at,
        )


def build_sla_service(
    db: AsyncSession,
    *,
    notification_service: NotificationService | None = None,
) -> SLAService:
    """
    Convenience factory wiring up every repository SLAService can use —
    every route that touches SLA clocks (directly, or indirectly via
    EmailService/InteractionService/InboxTicketService) constructs one
    of these rather than hand-assembling four repositories inline at
    each of the ~8 call sites.
    """

    return SLAService(
        sla_policy_repository=SLAPolicyRepository(db),
        first_response_sla_repository=FirstResponseSLARepository(db),
        resolution_sla_repository=ResolutionSLARepository(db),
        ticket_repository=TicketRepository(db),
        interaction_repository=InteractionRepository(db),
        notification_service=notification_service,
        client_repository=ClientRepository(db),
        user_repository=UserRepository(db),
        sla_breach_notification_repository=SLABreachNotificationRepository(db),
    )


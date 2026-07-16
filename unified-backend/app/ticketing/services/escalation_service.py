import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.notifications.service import NotificationService, NotificationType
from app.ticketing.enums import (
    TRIGGERED_BY_AUTO_SLA_BREACH,
    TRIGGERED_BY_MANUAL,
    CLOSED_REASON_TICKET_RESOLVED,
    ActorRole,
    AuditEntityType,
    AuditEventType,
    EscalationLevel,
    EscalationStatus,
    TicketPriority,
)
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.ticket import Ticket
from app.ticketing.models.ticket_escalation import TicketEscalation
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.resolution_sla_repository import ResolutionSLARepository
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_escalation_repository import (
    TicketEscalationRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.assignment import (
    AssignableAgentsResponse,
    AssignableGroup,
    AssignableUserSummary,
)
from app.ticketing.schemas.sla import TicketEscalationState
from app.ticketing.schemas.ticket import TicketUpdate
from app.ticketing.schemas.ticket_action import TicketActionResponse
from app.ticketing.services.access_control import (
    ACCOUNT_MANAGER_ROLE_NAME,
    GLOBAL_INBOX_ROLE_NAMES,
    SUPERVISOR_ROLE_NAMES,
    ensure_agent_can_view_ticket,
    ensure_has_permission,
    ensure_ticket_not_closed,
    has_permission,
)
from app.ticketing.services.assignment_service import STAFF_ROLE_NAME
from app.ticketing.services.escalation_handling_sla_service import (
    EscalationHandlingSlaService,
    build_escalation_handling_sla_service,
)
from app.ticketing.services.audit_log_service import AuditLogService
from app.ticketing.services.escalation_rules import next_level, resolve_manager_ids
from app.ticketing.services.sla_breach_notifier import (
    build_absolute_link,
    resolve_global_inbox_user_ids,
    send_notification_emails,
)
from app.ticketing.services.sla_escalation_rules import (
    TEAM_LEAD_ROLE_NAME,
    RecipientContext,
    resolve_team_lead,
)


def _to_assignable_group(role_name: str, users: list[User]) -> AssignableGroup:
    return AssignableGroup(
        role=role_name,
        users=[
            AssignableUserSummary(user_id=u.user_id, name=u.name) for u in users
        ],
    )

logger = logging.getLogger(__name__)

DEFAULT_ACK_TARGET_MINUTES = 30

#escalation_service.py

class EscalationService:
    """
    Owns the internal escalation ownership/acknowledgment workflow
    (TicketEscalation) — a chain of TEAM_LEAD -> MANAGER -> SITE_LEAD
    ownership hand-offs that starts only when a ticket is escalated
    (manually via ticket:escalate, or automatically the first time its
    Resolution SLA crosses BREACHED/ESCALATED with nothing already
    active) and advances only if the current owner ignores their
    acknowledgment window (waiting the full ack window at each level
    before moving to the next, via evaluate_overdue below).

    The STARTING level is not always TEAM_LEAD — see
    _resolve_starting_level: a Staff-owned (or unclaimed) ticket starts
    at TEAM_LEAD as usual, but a ticket already assigned to a Team Lead
    themselves starts one level up at MANAGER (Account Manager)
    instead, and one assigned to an Account Manager starts at
    SITE_LEAD — escalating "to" whoever already owns the ticket and
    isn't acting on it would just re-notify the same person.

    Never invents its own reshift math for the Resolution SLA clock —
    the two deliberate exceptions, split into three separate moments on
    purpose, are _set_ticket_priority_to_critical, acknowledge(), and
    _complete_acceptance (via _reshift_sla_for_escalation_acceptance):

    - _set_ticket_priority_to_critical runs immediately in
      _create_escalation (manual_escalate/auto_escalate_if_needed) — a
      ticket's priority (and every Critical badge/filter it drives)
      becomes CRITICAL the instant it escalates, full stop. This is a
      plain Ticket.current_priority write; it never touches the
      Resolution SLA clock itself.
    - acknowledge() only stops the ack-window auto-advance
      (evaluate_overdue only considers ACTIVE escalations) — it does
      NOT reshift the Resolution SLA and does NOT start the
      escalation-handling SLA. Acknowledging alone means "someone is
      looking at this," not "someone has taken it on."
    - _complete_acceptance (called from acknowledge_via_assignment —
      i.e. claim_ticket/transfer_agent — and from confirm_assignment)
      is the one place both the Resolution SLA reshift and the
      escalation-handling SLA's start actually happen, once a
      supervisor has *also* settled who the ticket is assigned to.
      This is the "Resolution SLA starts only after Acknowledge AND
      Assign" requirement: acknowledging and then never assigning
      anyone leaves the clock parked at its pre-escalation target
      indefinitely, by design.

    Escalating a ticket, and even acknowledging it, must leave the
    Resolution SLA's own started_at/due_at/status completely untouched
    until assignment is also settled; every other method in this class
    only reads a ResolutionSLA (to snapshot resolution_sla_id for
    display, or to resolve the escalation's ack window off the
    ticket's priority-matched SLAPolicy row).
    """

    def __init__(
        self,
        *,
        ticket_escalation_repository: TicketEscalationRepository,
        ticket_repository: TicketRepository,
        resolution_sla_repository: ResolutionSLARepository,
        sla_policy_repository: SLAPolicyRepository,
        user_repository: UserRepository,
        notification_service: NotificationService | None = None,
        escalation_handling_sla_service: EscalationHandlingSlaService | None = None,
    ):
        self.ticket_escalation_repository = ticket_escalation_repository
        self.ticket_repository = ticket_repository
        self.resolution_sla_repository = resolution_sla_repository
        self.sla_policy_repository = sla_policy_repository
        self.user_repository = user_repository
        self.notification_service = notification_service
        # Optional so existing callers/tests that construct this
        # service directly (see tests/test_escalation_service.py) keep
        # working unchanged — every call site below no-ops the
        # handling-SLA side effect when this is None, same convention
        # as notification_service above.
        self.escalation_handling_sla_service = escalation_handling_sla_service

    # ---------------------------------------------------------
    # Owner resolution
    # ---------------------------------------------------------

    async def _resolve_owners_for_level(
        self, *, level: EscalationLevel, ticket: Ticket
    ) -> set[UUID]:
        """
        TEAM_LEAD reuses sla_escalation_rules.resolve_team_lead's exact
        claimed/unclaimed logic (self-claim edge cases included) — the
        same "who is this ticket's Team Lead" question the Resolution
        SLA notification ladder already answers, asked here for
        ownership instead of just notification. MANAGER walks one more
        hop up the reporting line (see escalation_rules.resolve_manager_ids).
        SITE_LEAD is the same GLOBAL_INBOX (Site Lead + Super Admin)
        used everywhere else in this codebase's SLA code.
        """

        if level == EscalationLevel.SITE_LEAD:
            return await resolve_global_inbox_user_ids(self.user_repository)

        if ticket.agent_id is not None:
            assigned_agent = await self.user_repository.get_by_id(ticket.agent_id)
            ctx = RecipientContext(assigned_agent=assigned_agent)
        else:
            team_leads = await self.user_repository.list_active_by_role_and_category(
                TEAM_LEAD_ROLE_NAME, ticket.ticket_type
            )
            ctx = RecipientContext(team_leads=team_leads)

        team_lead_ids = resolve_team_lead(ctx)

        if level == EscalationLevel.TEAM_LEAD:
            return team_lead_ids

        # MANAGER
        if not team_lead_ids:
            return set()
        team_lead_users = await self.user_repository.list_by_ids(list(team_lead_ids))
        return resolve_manager_ids(team_lead_users)

    async def _resolve_owners_with_fallback(
        self, *, starting_level: EscalationLevel, ticket: Ticket
    ) -> tuple[EscalationLevel, set[UUID]]:
        """
        Skips forward through the chain if a level resolves to nobody
        (e.g. an unclaimed ticket in a category with no Team Lead
        assigned yet) rather than creating an escalation nobody can
        act on — same "degrade safely, never raise" convention as
        sla_escalation_rules.resolve_recipients.
        """

        level: EscalationLevel | None = starting_level
        while level is not None:
            owners = await self._resolve_owners_for_level(level=level, ticket=ticket)
            if owners:
                return level, owners
            level = next_level(level)

        logger.warning(
            "Escalation for ticket %s resolved to zero owners at every level "
            "(no Team Lead/Manager/Site Lead could be found).",
            ticket.ticket_id,
        )
        return EscalationLevel.SITE_LEAD, set()

    async def _ack_target_minutes(self, priority: TicketPriority) -> int:
        policy = await self.sla_policy_repository.get_by_priority(priority)
        return (
            policy.escalation_ack_target_minutes
            if policy is not None
            else DEFAULT_ACK_TARGET_MINUTES
        )

    # ---------------------------------------------------------
    # Notification
    # ---------------------------------------------------------

    async def _notify_owners(
        self,
        *,
        ticket: Ticket,
        owner_ids: set[UUID],
        notification_type: str,
        title: str,
        message: str,
    ) -> None:
        if not owner_ids:
            return

        if self.notification_service is not None:
            await self.notification_service.notify(
                owner_ids,
                notification_type,
                title=title,
                message=message,
                link=f"/tickets/{ticket.ticket_id}",
                related_entity_type="ticket",
                related_entity_id=ticket.ticket_id,
            )

        await send_notification_emails(
            recipient_ids=owner_ids,
            subject=title,
            body=f"{message}\n\nView it here: {build_absolute_link(f'/tickets/{ticket.ticket_id}')}",
            user_repository=self.user_repository,
        )

    # ---------------------------------------------------------
    # Create — manual (ticket:escalate) and automatic (SLA breach)
    # ---------------------------------------------------------

    async def manual_escalate(
        self, ticket_id: UUID, current_user: User
    ) -> TicketActionResponse:
        ticket = await self.ticket_repository.get_by_id(ticket_id)
        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found."
            )

        ensure_agent_can_view_ticket(ticket, current_user)
        ensure_has_permission(current_user, "ticket:escalate")
        ensure_ticket_not_closed(ticket)

        existing = await self.ticket_escalation_repository.get_active_by_ticket_id(
            ticket_id
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This ticket already has an active escalation.",
            )

        resolution_clock = await self.resolution_sla_repository.get_by_ticket_id(
            ticket_id
        )

        escalation = await self._create_escalation(
            ticket=ticket,
            resolution_clock=resolution_clock,
            triggered_by=TRIGGERED_BY_MANUAL,
            triggered_by_user_id=current_user.user_id,
        )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )
        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.ESCALATION_CREATED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={
                "level": escalation.level.value,
                "owner_ids": escalation.owner_ids,
                "triggered_by": TRIGGERED_BY_MANUAL,
            },
        )

        await self._notify_owners(
            ticket=ticket,
            owner_ids={UUID(u) for u in escalation.owner_ids},
            notification_type=NotificationType.ESCALATION_CREATED,
            title=f"Ticket Escalated: {ticket.title}",
            message=(
                f"{current_user.name} escalated ticket \"{ticket.title}\" "
                f"({ticket.current_priority.value} priority) to "
                f"{escalation.level.value.replace('_', ' ').title()}.\n\n"
                f"Please acknowledge by {escalation.ack_due_at.strftime('%Y-%m-%d %H:%M UTC')} "
                "— if this isn't acknowledged in time, it will automatically "
                "advance to the next level."
            ),
        )

        return TicketActionResponse(
            interaction_id=None,
            ticket_id=ticket_id,
            message="Ticket escalated.",
            created_at=escalation.created_at,
        )

    async def auto_escalate_if_needed(
        self, *, ticket: Ticket, resolution_clock: ResolutionSLA | None
    ) -> bool:
        """
        Called from SLASweepService the first time a Resolution SLA
        clock crosses BREACHED/ESCALATED — a no-op if this ticket
        already has an active escalation (manual or automatic), so a
        supervisor who pre-emptively escalated before the breach (see
        the spec's own 12:30-escalation-before-13:00-breach example)
        never gets a second, redundant chain created underneath them.
        Returns whether a new escalation was actually created, so the
        sweep can tally it into SLASweepResponse.
        """

        existing = await self.ticket_escalation_repository.get_active_by_ticket_id(
            ticket.ticket_id
        )
        if existing is not None:
            return False

        escalation = await self._create_escalation(
            ticket=ticket,
            resolution_clock=resolution_clock,
            triggered_by=TRIGGERED_BY_AUTO_SLA_BREACH,
            triggered_by_user_id=None,
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket.ticket_id,
            event_type=AuditEventType.ESCALATION_CREATED,
            actor_id=None,
            actor_name="SLA Sweep",
            actor_role=ActorRole.SYSTEM,
            new_values={
                "level": escalation.level.value,
                "owner_ids": escalation.owner_ids,
                "triggered_by": TRIGGERED_BY_AUTO_SLA_BREACH,
            },
        )

        await self._notify_owners(
            ticket=ticket,
            owner_ids={UUID(u) for u in escalation.owner_ids},
            notification_type=NotificationType.ESCALATION_CREATED,
            title=f"Ticket Auto-Escalated: {ticket.title}",
            message=(
                f"Ticket \"{ticket.title}\" ({ticket.current_priority.value} priority) "
                "breached its Resolution SLA with no active escalation, so it was "
                f"automatically escalated to {escalation.level.value.replace('_', ' ').title()}.\n\n"
                f"Please acknowledge by {escalation.ack_due_at.strftime('%Y-%m-%d %H:%M UTC')} "
                "— if this isn't acknowledged in time, it will automatically "
                "advance to the next level."
            ),
        )

        return True

    async def _set_ticket_priority_to_critical(self, ticket: Ticket) -> None:
        """
        A ticket's priority permanently becomes CRITICAL the moment it
        escalates (manual or automatic) — immediately, not deferred to
        acknowledgment. This is a plain display/filterable-priority
        change only: it deliberately does NOT touch the Resolution SLA
        clock (started_at/due_at/priority) — see
        _reshift_sla_for_escalation_acceptance below for that, which is
        the one piece still deferred to acknowledge()/
        acknowledge_via_assignment(). Splitting these two used to be
        one combined action; they're split because "the ticket shows as
        Critical/escalated right away" and "the SLA timer actually
        restarts against the Critical target" are different moments in
        the required workflow — the ticket's own priority label (and
        the Critical badge it drives everywhere in the UI) must reflect
        reality the instant escalation happens, while the clock itself
        must keep measuring time honestly against whoever hasn't yet
        taken ownership.

        No-op if already CRITICAL (idempotent — re-escalating an
        already-critical ticket, e.g. after an ack-window advance to
        the next level, must never write a second redundant audit row).
        """

        if ticket.current_priority == TicketPriority.CRITICAL:
            return

        old_priority = ticket.current_priority
        await self.ticket_repository.update(
            ticket, TicketUpdate(current_priority=TicketPriority.CRITICAL)
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket.ticket_id,
            event_type=AuditEventType.PRIORITY_CHANGED,
            actor_id=None,
            actor_name="Escalation workflow",
            actor_role=ActorRole.SYSTEM,
            old_values={"current_priority": old_priority.value},
            new_values={"current_priority": TicketPriority.CRITICAL.value, "reason": "escalated"},
        )

    async def _reshift_sla_for_escalation_acceptance(self, ticket: Ticket) -> None:
        """
        The Resolution SLA clock only reshifts onto CRITICAL's target
        once a supervisor has actually taken ownership of the
        escalation — acknowledged (acknowledge()), or assigned before
        ever being acknowledged (acknowledge_via_assignment()) — never
        at escalation creation itself, even though the ticket's own
        priority label already flipped to CRITICAL then (see
        _set_ticket_priority_to_critical above). This is the "the
        Resolution SLA should NOT start immediately when escalated —
        only after acknowledgment AND assignment" requirement: the
        clock keeps measuring the *original* target's honest overdue
        time for as long as the escalation sits unacknowledged, and
        only restarts against the tighter CRITICAL target the moment
        someone takes it on.

        Reshifts through SLAService.reshift_resolution_clock_for_
        priority_change — the exact same method a manual Change
        Priority action already uses — rather than inventing a
        parallel code path, so the sweep's own elapsed-fraction math
        (keyed off ResolutionSLA.priority, not Ticket.current_priority)
        stays internally consistent. No-op if the clock has already
        been reshifted onto CRITICAL (idempotent — acknowledging via
        assignment and then again via a literal Acknowledge click, or a
        later reassignment, must never re-reshift the clock a second
        time) or if there's no clock to reshift at all. Deferred import
        to avoid a circular import (sla_service.py imports
        build_escalation_service from this module at module level).
        """

        clock = await self.resolution_sla_repository.get_by_ticket_id(ticket.ticket_id)
        if clock is None or clock.priority == TicketPriority.CRITICAL:
            return

        from app.ticketing.services.sla_service import build_sla_service

        sla_service = build_sla_service(self.ticket_repository.db)
        await sla_service.reshift_resolution_clock_for_priority_change(
            ticket_id=ticket.ticket_id, new_priority=TicketPriority.CRITICAL
        )

    async def _resolve_starting_level(self, ticket: Ticket) -> EscalationLevel:
        """
        Escalation starts one level above whoever currently owns (or
        would own) the ticket — notifying someone who's already
        sitting on it and evidently not acting achieves nothing. An
        unclaimed ticket, or one assigned to Staff, starts at the
        normal TEAM_LEAD floor. A ticket already assigned to a Team
        Lead themselves (they claimed it directly, or a prior
        escalation assigned it to them) skips straight to MANAGER
        (Account Manager) — re-notifying the same Team Lead who
        already owns it would be pointless. A ticket assigned to an
        Account Manager skips straight to SITE_LEAD for the same
        reason. Site Lead/Super Admin are already the terminal level;
        no further level exists above them to start at, so this falls
        back to TEAM_LEAD in that case (the fallback chain in
        _resolve_owners_with_fallback will still resolve correctly
        off the ticket's own category/client, same as an ordinary
        Staff-owned ticket) rather than inventing a level this ladder
        doesn't have.
        """

        if ticket.agent_id is None:
            return EscalationLevel.TEAM_LEAD

        agent = await self.user_repository.get_by_id(ticket.agent_id)
        if agent is None:
            return EscalationLevel.TEAM_LEAD

        role_name = agent.role.name
        if role_name == TEAM_LEAD_ROLE_NAME:
            return EscalationLevel.MANAGER
        if role_name == ACCOUNT_MANAGER_ROLE_NAME:
            return EscalationLevel.SITE_LEAD
        return EscalationLevel.TEAM_LEAD

    async def _create_escalation(
        self,
        *,
        ticket: Ticket,
        resolution_clock: ResolutionSLA | None,
        triggered_by: str,
        triggered_by_user_id: UUID | None,
    ) -> TicketEscalation:
        # The ticket's priority becomes CRITICAL immediately — before
        # resolving owners/ack-window below, so a freshly-escalated
        # ticket's own ack window is CRITICAL's (tighter) one right
        # away, not its previous priority's. The Resolution SLA clock
        # itself is untouched here — see
        # _reshift_sla_for_escalation_acceptance's own docstring for
        # why that part waits for acknowledge/assignment.
        await self._set_ticket_priority_to_critical(ticket)

        now = datetime.now(timezone.utc)
        starting_level = await self._resolve_starting_level(ticket)
        level, owner_ids = await self._resolve_owners_with_fallback(
            starting_level=starting_level, ticket=ticket
        )
        ack_minutes = await self._ack_target_minutes(ticket.current_priority)

        return await self.ticket_escalation_repository.create(
            ticket_id=ticket.ticket_id,
            resolution_sla_id=(
                resolution_clock.resolution_sla_id if resolution_clock is not None else None
            ),
            level=level,
            owner_ids=owner_ids,
            triggered_by=triggered_by,
            triggered_by_user_id=triggered_by_user_id,
            ack_due_at=now + timedelta(minutes=ack_minutes),
            now=now,
        )

    # ---------------------------------------------------------
    # Acknowledge
    # ---------------------------------------------------------

    async def acknowledge(
        self, ticket_id: UUID, current_user: User
    ) -> TicketActionResponse:
        ticket = await self.ticket_repository.get_by_id(ticket_id)
        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found."
            )
        ensure_agent_can_view_ticket(ticket, current_user)

        escalation = await self.ticket_escalation_repository.get_active_by_ticket_id(
            ticket_id
        )
        if escalation is None or escalation.status != EscalationStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="There is no active escalation awaiting acknowledgment on this ticket.",
            )

        # Strictly owner_ids membership — no Site Lead/Super Admin
        # "global overseer" bypass here, unlike most other visibility
        # checks in this codebase. A Site Lead/Super Admin only
        # becomes a real owner once the chain actually reaches
        # SITE_LEAD (resolve_global_inbox_user_ids populates owner_ids
        # for them at that point) — allowing them to acknowledge
        # earlier would let them jump the queue on a TEAM_LEAD/MANAGER-
        # level escalation that hasn't reached them yet, exactly the
        # "escalation should happen one level at a time" behavior this
        # check exists to guarantee. Mirrors the same owner_ids-only
        # rule the Escalated tab's own visibility query now enforces
        # (TicketRepository._escalated_owner_condition).
        if str(current_user.user_id) not in escalation.owner_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the current escalation owner can acknowledge it.",
            )

        now = datetime.now(timezone.utc)
        updated = await self.ticket_escalation_repository.acknowledge(
            escalation, acknowledged_by=current_user.user_id, at=now
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This escalation was already acknowledged or closed.",
            )

        # Deliberately does NOT call _reshift_sla_for_escalation_acceptance
        # or start the escalation-handling SLA here — acknowledging
        # alone only stops the ack-window auto-advance (evaluate_overdue
        # only ever considers ACTIVE escalations, and this one just
        # left that state). The Resolution SLA/handling SLA only start
        # once assignment is *also* settled — see _complete_acceptance,
        # called from acknowledge_via_assignment (claim/transfer) and
        # confirm_assignment (the "keep the current assignee" case) —
        # so that "Resolution SLA starts only after Acknowledge AND
        # Assign" holds even if a supervisor acknowledges and then
        # never gets around to picking an assignee.
        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )
        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.ESCALATION_ACKNOWLEDGED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={"level": escalation.level.value},
        )

        return TicketActionResponse(
            interaction_id=None,
            ticket_id=ticket_id,
            message="Escalation acknowledged — select who this ticket should be assigned to.",
            created_at=now,
        )

    # ---------------------------------------------------------
    # Acceptance completion — the one moment the Resolution SLA and
    # the escalation-handling SLA actually start, reached from three
    # different frontend actions that all mean the same thing ("who
    # owns this going forward is now settled"): claiming an unclaimed
    # ticket, transferring it to someone else, or explicitly confirming
    # it stays with its current assignee. Acknowledging alone
    # (acknowledge() above) never reaches this — see that method's own
    # docstring for why.
    # ---------------------------------------------------------

    async def _complete_acceptance(
        self,
        *,
        ticket: Ticket,
        escalation: TicketEscalation,
        current_user: User,
        via: str,
    ) -> TicketEscalation:
        """
        Idempotent and safe to call more than once for the same
        escalation (e.g. acknowledge() already ran, or a later
        reassignment reaches this a second time) — acknowledging a
        second time here is a no-op (repository.acknowledge only acts
        on ACTIVE, returns None otherwise), the SLA reshift no-ops once
        the clock is already on CRITICAL, and the handling-SLA start is
        itself idempotent per its own docstring.
        """

        now = datetime.now(timezone.utc)
        updated = await self.ticket_escalation_repository.acknowledge(
            escalation, acknowledged_by=current_user.user_id, at=now
        )
        if updated is None:
            # Already acknowledged (the ordinary case: step 1's
            # explicit Acknowledge click already ran) or closed — use
            # the escalation as already loaded rather than treating
            # this as an error.
            updated = escalation

        # The one moment the Resolution SLA clock actually reshifts
        # onto CRITICAL's target — see that method's own docstring.
        await self._reshift_sla_for_escalation_acceptance(ticket)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )
        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket.ticket_id,
            event_type=AuditEventType.ESCALATION_ACKNOWLEDGED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={"level": escalation.level.value, "via": via},
        )

        if self.escalation_handling_sla_service is not None:
            await self.escalation_handling_sla_service.start_if_not_started(
                escalation=updated, ticket=ticket
            )

        return updated

    # ---------------------------------------------------------
    # Acknowledge via assignment — a supervisor claiming/transferring
    # an escalated ticket is treated as accepting it, same as a literal
    # Acknowledge click followed by a real assignment decision.
    # Deliberately more permissive than acknowledge() itself: the
    # assigning supervisor need not already be a listed escalation
    # owner, since the act of assigning is itself the acceptance
    # signal — mirrors ensure_can_reassign_ticket's own authorization
    # (supervisor role, or ticket:transfer permission).
    # ---------------------------------------------------------

    async def acknowledge_via_assignment(
        self, ticket_id: UUID, current_user: User
    ) -> None:
        """
        Called from InteractionService.transfer_agent and .claim_ticket
        right after a successful staff assignment/claim. A no-op —
        never raises — if there's no non-CLOSED escalation on this
        ticket at all: assigning a ticket that has no/already-closed
        escalation is completely ordinary, not an error. Unlike
        acknowledge(), this does not gate on the caller already being
        a resolved owner — the caller's own authorization (transfer_agent's
        ensure_can_reassign_ticket, or claim_ticket's own rules) already
        authorized this actor to take the ticket in the first place.

        Deliberately reachable whether the escalation is still ACTIVE
        (assigning before ever clicking Acknowledge — assignment alone
        counts as acceptance) or already ACKNOWLEDGED (the ordinary
        two-step case: Acknowledge was clicked first, and this is the
        follow-up Assign step) — get_active_by_ticket_id already
        excludes only CLOSED, so no extra status check is needed here.
        """

        if current_user.role.name not in SUPERVISOR_ROLE_NAMES and not has_permission(
            current_user, "ticket:transfer"
        ):
            return

        escalation = await self.ticket_escalation_repository.get_active_by_ticket_id(
            ticket_id
        )
        if escalation is None:
            return

        ticket = await self.ticket_repository.get_by_id(ticket_id)
        if ticket is None:
            return

        await self._complete_acceptance(
            ticket=ticket, escalation=escalation, current_user=current_user, via="assignment"
        )

    # ---------------------------------------------------------
    # Confirm assignment — the one confirmAssignment() branch on the
    # frontend that neither claims nor transfers (the acknowledging
    # supervisor decides the ticket should stay with its current
    # assignee) — without this, that branch would leave the Resolution
    # SLA/handling SLA never started at all, since it never reaches
    # claim_ticket or transfer_agent.
    # ---------------------------------------------------------

    async def confirm_assignment(
        self, ticket_id: UUID, current_user: User
    ) -> TicketActionResponse:
        """
        Unlike acknowledge_via_assignment (a permissive safety net for
        its two internal callers), this is a directly user-invoked
        endpoint and fails loudly with the same authorization
        acknowledge() itself applies — only the escalation's own listed
        owner(s), or a company-wide overseer, may confirm it.
        """

        ticket = await self.ticket_repository.get_by_id(ticket_id)
        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found."
            )
        ensure_agent_can_view_ticket(ticket, current_user)

        escalation = await self.ticket_escalation_repository.get_active_by_ticket_id(
            ticket_id
        )
        if escalation is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="There is no active escalation on this ticket.",
            )

        # Strictly owner_ids membership — see acknowledge()'s own
        # comment for why there is deliberately no Site Lead/Super
        # Admin bypass here either.
        if str(current_user.user_id) not in escalation.owner_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the current escalation owner can confirm this assignment.",
            )

        now = datetime.now(timezone.utc)
        await self._complete_acceptance(
            ticket=ticket,
            escalation=escalation,
            current_user=current_user,
            via="confirmed_unchanged",
        )

        return TicketActionResponse(
            interaction_id=None,
            ticket_id=ticket_id,
            message="Assignment confirmed.",
            created_at=now,
        )

    # ---------------------------------------------------------
    # Acknowledge candidates — who the caller may hand this escalated
    # ticket to, role-scoped (see the plan's own role table): the
    # candidate set is a different concept per acting role, not one
    # flat list everyone shares.
    # ---------------------------------------------------------

    async def get_acknowledge_candidates(
        self, ticket_id: UUID, current_user: User
    ) -> AssignableAgentsResponse:
        """
        Site Lead/Super Admin choose between the ticket's category Team
        Lead(s) and the Account Manager who owns the ticket's client
        (Client.account_manager_id — client ownership is the only real
        AM-scoping concept in this data model, there is no "AM of a
        category"). Account Manager chooses among their own reporting
        Team Leads who also match the ticket's category. Team Lead
        chooses among the ticket's category Staff — identical to the
        flat listAgents(category) list this replaced, just reshaped
        into a role-labeled group. The caller's own "assign to myself"
        option is the separate `me` field, never included in `groups`.
        """

        ticket = await self.ticket_repository.get_by_id(ticket_id)
        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found."
            )
        ensure_agent_can_view_ticket(ticket, current_user)

        groups: list[AssignableGroup] = []
        role_name = current_user.role.name

        if role_name in GLOBAL_INBOX_ROLE_NAMES:
            team_leads = await self.user_repository.list_active_by_role_and_category(
                TEAM_LEAD_ROLE_NAME, ticket.ticket_type
            )
            groups.append(_to_assignable_group(TEAM_LEAD_ROLE_NAME, team_leads))

            client_repository = ClientRepository(self.ticket_repository.db)
            client = (
                await client_repository.get_by_id(ticket.client_company_id)
                if ticket.client_company_id is not None
                else None
            )
            if client is not None:
                account_manager = await self.user_repository.get_by_id(
                    client.account_manager_id
                )
                if account_manager is not None and account_manager.is_active:
                    groups.append(
                        _to_assignable_group(ACCOUNT_MANAGER_ROLE_NAME, [account_manager])
                    )

        elif role_name == ACCOUNT_MANAGER_ROLE_NAME:
            team_leads = await self.user_repository.list_active_by_role_and_category(
                TEAM_LEAD_ROLE_NAME, ticket.ticket_type
            )
            team_leads = [tl for tl in team_leads if tl.manager_id == current_user.user_id]
            groups.append(_to_assignable_group(TEAM_LEAD_ROLE_NAME, team_leads))

        elif role_name == TEAM_LEAD_ROLE_NAME:
            staff = await self.user_repository.list_active_by_role_and_category(
                STAFF_ROLE_NAME, ticket.ticket_type
            )
            groups.append(_to_assignable_group(STAFF_ROLE_NAME, staff))

        return AssignableAgentsResponse(
            me=AssignableUserSummary(user_id=current_user.user_id, name=current_user.name),
            groups=[g for g in groups if g.users],
        )

    # ---------------------------------------------------------
    # Sweep hook — advance any ACTIVE escalation past its ack window
    # ---------------------------------------------------------

    async def evaluate_overdue(self, *, now: datetime) -> int:
        """
        Called from SLASweepService.run_sweep, alongside (not instead
        of) its existing threshold sweep — extends the same background
        worker rather than adding a second scheduler. Advances every
        ACTIVE escalation whose ack_due_at has passed; an already-
        terminal SITE_LEAD escalation just gets re-notified with a
        fresh ack window instead of advancing further. Returns how
        many rows were advanced (surfaced in SLASweepResponse).
        """

        overdue = await self.ticket_escalation_repository.list_overdue_active(now=now)
        advanced = 0

        for escalation in overdue:
            ticket = await self.ticket_repository.get_by_id(escalation.ticket_id)
            if ticket is None:
                continue

            old_level = escalation.level
            upcoming = next_level(old_level)
            target_level = upcoming if upcoming is not None else old_level

            new_level, owner_ids = await self._resolve_owners_with_fallback(
                starting_level=target_level, ticket=ticket
            )
            ack_minutes = await self._ack_target_minutes(ticket.current_priority)
            new_ack_due_at = now + timedelta(minutes=ack_minutes)

            await self.ticket_escalation_repository.advance(
                escalation,
                new_level=new_level,
                owner_ids=owner_ids,
                ack_due_at=new_ack_due_at,
                now=now,
            )
            advanced += 1

            await AuditLogService.log_event(
                self.ticket_repository.db,
                entity_type=AuditEntityType.TICKET,
                entity_id=ticket.ticket_id,
                event_type=AuditEventType.ESCALATION_ADVANCED,
                actor_id=None,
                actor_name="SLA Sweep",
                actor_role=ActorRole.SYSTEM,
                old_values={"level": old_level.value},
                new_values={"level": new_level.value, "owner_ids": [str(u) for u in owner_ids]},
            )

            await self._notify_owners(
                ticket=ticket,
                owner_ids=owner_ids,
                notification_type=NotificationType.ESCALATION_ADVANCED,
                title=f"Escalation Advanced: {ticket.title}",
                message=(
                    f"Ticket \"{ticket.title}\" ({ticket.current_priority.value} priority) was not "
                    f"acknowledged by {old_level.value.replace('_', ' ').title()} in time, and has "
                    f"advanced to {new_level.value.replace('_', ' ').title()}.\n\n"
                    f"Please acknowledge by {new_ack_due_at.strftime('%Y-%m-%d %H:%M UTC')} "
                    "— if this isn't acknowledged in time, it will automatically "
                    "advance further."
                ),
            )

        return advanced

    # ---------------------------------------------------------
    # Sweep hook — advance ownership when the *handling* SLA (not the
    # ack window evaluate_overdue above guards) breaches
    # ---------------------------------------------------------

    async def advance_for_handling_sla_breach(self, ticket_id: UUID) -> bool:
        """
        Called from SLASweepService once per ticket whose
        EscalationHandlingSLA has just been marked breached (see
        EscalationHandlingSlaService.evaluate_breaches) — a distinct
        trigger from evaluate_overdue's ack-window check above (a
        handling-SLA breach means "acknowledged, but not actually
        resolved in time," not "never acknowledged at all"), so it's
        kept as its own method rather than folded into that one.
        Mirrors evaluate_overdue's own per-item advance shape (next
        level, re-notify at terminal SITE_LEAD) rather than sharing
        code with it, since the two are triggered by different
        deadlines and evaluate_overdue's exact behavior is directly
        asserted by tests/test_escalation_service.py — safer to keep
        them independent than risk changing that method's behavior.

        No-op (returns False) if the ticket's escalation is no longer
        active (already closed — e.g. the ticket was resolved in the
        same window) or doesn't exist at all.
        """

        escalation = await self.ticket_escalation_repository.get_active_by_ticket_id(
            ticket_id
        )
        if escalation is None:
            return False

        ticket = await self.ticket_repository.get_by_id(ticket_id)
        if ticket is None:
            return False

        now = datetime.now(timezone.utc)
        old_level = escalation.level
        upcoming = next_level(old_level)
        target_level = upcoming if upcoming is not None else old_level

        new_level, owner_ids = await self._resolve_owners_with_fallback(
            starting_level=target_level, ticket=ticket
        )
        ack_minutes = await self._ack_target_minutes(ticket.current_priority)
        new_ack_due_at = now + timedelta(minutes=ack_minutes)

        await self.ticket_escalation_repository.advance(
            escalation,
            new_level=new_level,
            owner_ids=owner_ids,
            ack_due_at=new_ack_due_at,
            now=now,
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket.ticket_id,
            event_type=AuditEventType.ESCALATION_ADVANCED,
            actor_id=None,
            actor_name="SLA Sweep",
            actor_role=ActorRole.SYSTEM,
            old_values={"level": old_level.value},
            new_values={
                "level": new_level.value,
                "owner_ids": [str(u) for u in owner_ids],
                "reason": "escalation_handling_sla_breach",
            },
        )

        await self._notify_owners(
            ticket=ticket,
            owner_ids=owner_ids,
            notification_type=NotificationType.ESCALATION_ADVANCED,
            title=f"Escalation Handling SLA Breached: {ticket.title}",
            message=(
                f"Ticket \"{ticket.title}\" ({ticket.current_priority.value} priority) was "
                f"acknowledged but not resolved within its escalation-handling window. "
                f"Ownership has advanced from {old_level.value.replace('_', ' ').title()} "
                f"to {new_level.value.replace('_', ' ').title()}.\n\n"
                f"Please acknowledge by {new_ack_due_at.strftime('%Y-%m-%d %H:%M UTC')} "
                "— if this isn't acknowledged in time, it will automatically "
                "advance further."
            ),
        )

        return True

    # ---------------------------------------------------------
    # Close — hooked off Resolution SLA completion, never off a
    # timer of its own
    # ---------------------------------------------------------

    async def close_for_ticket_resolution(self, ticket_id: UUID) -> None:
        """
        Called from SLAService.complete_resolution_clock (the same
        chokepoint that completes the Resolution SLA when a supervisor
        closes a ticket) — an escalation never outlives the ticket it
        was raised on. A no-op if there is no active escalation.
        """

        escalation = await self.ticket_escalation_repository.get_active_by_ticket_id(
            ticket_id
        )
        if escalation is None:
            return

        now = datetime.now(timezone.utc)
        closed = await self.ticket_escalation_repository.close(
            escalation, reason=CLOSED_REASON_TICKET_RESOLVED, at=now
        )
        if closed is None:
            return

        await AuditLogService.log_event(
            self.ticket_escalation_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.ESCALATION_CLOSED,
            actor_id=None,
            actor_name="System",
            actor_role=ActorRole.SYSTEM,
            new_values={"reason": CLOSED_REASON_TICKET_RESOLVED},
        )

        # Closing the escalation also completes its handling clock, if
        # one was ever started — no-op otherwise (see
        # EscalationHandlingSlaService.complete_for_escalation's own
        # docstring). This never touches ResolutionSLA itself, same as
        # every other line in this method.
        if self.escalation_handling_sla_service is not None:
            await self.escalation_handling_sla_service.complete_for_escalation(
                escalation.escalation_id
            )

    # ---------------------------------------------------------
    # Read state
    # ---------------------------------------------------------

    async def get_escalation_state(
        self, ticket_id: UUID
    ) -> TicketEscalationState | None:
        escalation = await self.ticket_escalation_repository.get_active_by_ticket_id(
            ticket_id
        )
        if escalation is None:
            return None

        owner_uuids = [UUID(s) for s in escalation.owner_ids]
        names_by_id = await self.user_repository.get_names_by_ids(owner_uuids)
        owner_names = [names_by_id.get(uid, "Unknown") for uid in owner_uuids]

        now = datetime.now(timezone.utc)
        overdue_seconds = (
            (now - escalation.ack_due_at).total_seconds()
            if escalation.status == EscalationStatus.ACTIVE and escalation.ack_due_at < now
            else 0.0
        )

        return TicketEscalationState(
            escalation_id=escalation.escalation_id,
            level=escalation.level,
            status=escalation.status,
            owner_ids=owner_uuids,
            owner_names=owner_names,
            triggered_by=escalation.triggered_by,
            created_at=escalation.created_at,
            level_started_at=escalation.level_started_at,
            ack_due_at=escalation.ack_due_at,
            acknowledged_at=escalation.acknowledged_at,
            closed_at=escalation.closed_at,
            closed_reason=escalation.closed_reason,
            overdue_seconds=overdue_seconds,
        )


def build_escalation_service(
    db: AsyncSession,
    *,
    notification_service: NotificationService | None = None,
) -> EscalationService:
    return EscalationService(
        ticket_escalation_repository=TicketEscalationRepository(db),
        ticket_repository=TicketRepository(db),
        resolution_sla_repository=ResolutionSLARepository(db),
        sla_policy_repository=SLAPolicyRepository(db),
        user_repository=UserRepository(db),
        notification_service=notification_service,
        escalation_handling_sla_service=build_escalation_handling_sla_service(db),
    )

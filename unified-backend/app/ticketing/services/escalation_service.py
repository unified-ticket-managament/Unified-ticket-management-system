import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.notifications.service import NotificationService, NotificationType
from app.ticketing.enums import (
    OWNER_ROLE_REPORTING_MANAGER,
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
from app.ticketing.repositories.audit_log_repository import AuditLogRepository
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
    AGENT_ROLE_NAMES,
    SITE_LEAD_ROLE_NAME,
    STAFF_ROLE_NAME,
    SUPER_ADMIN_ROLE_NAME,
    SUPERVISOR_ROLE_NAMES,
    TEAM_LEAD_ROLE_NAME,
    ensure_agent_can_view_ticket,
    ensure_can_reassign_ticket,
    ensure_ticket_not_closed,
    has_permission,
)
from app.ticketing.services.escalation_handling_sla_service import (
    EscalationHandlingSlaService,
    build_escalation_handling_sla_service,
)
from app.ticketing.services.audit_log_service import AuditLogService
from app.ticketing.services.escalation_rules import (
    build_chain_owner_ids,
    resolve_owners_for_chain,
)
from app.ticketing.services.sla_breach_notifier import (
    build_absolute_link,
    resolve_global_inbox_user_ids,
    send_notification_emails,
)


def _to_assignable_group(role_name: str, users: list[User]) -> AssignableGroup:
    return AssignableGroup(
        role=role_name,
        users=[
            AssignableUserSummary(
                user_id=u.user_id,
                name=u.name,
                employee_number=u.employee_number,
                is_on_leave=u.is_on_leave,
            )
            for u in users
        ],
    )

logger = logging.getLogger(__name__)

DEFAULT_ACK_TARGET_MINUTES = 30

# Fallback only — used if a priority somehow has no SLAPolicy row at
# all (shouldn't happen against a properly seeded database). Mirrors
# DEFAULT_ACK_TARGET_MINUTES's own convention.
DEFAULT_HANDLING_STAGE_TARGET_MINUTES = 60

#escalation_service.py

class EscalationService:
    """
    Owns the internal escalation ownership/acknowledgment workflow
    (TicketEscalation) — an ownership hand-off chain that starts only
    when a ticket is escalated (manually via ticket:escalate, or
    automatically the first time its Resolution SLA crosses ESCALATED —
    now the sole terminal tier, at 100% elapsed, with nothing already
    active — the SLA lifecycle no longer has a separate BREACHED tier
    at 100%: hitting 100% *is* ESCALATED, and the escalation is created
    immediately rather than deferred to a later 150% crossing) and
    advances only if the current owner ignores their acknowledgment
    window (waiting the full ack window at each step before moving to
    the next, via evaluate_overdue below).

    Routing follows the ticket's own assignment history, not role
    hierarchy — see escalation_rules.build_chain_owner_ids/
    resolve_owners_for_chain and root CLAUDE.md's "SLA & Escalation"
    section for the full design. In short: the first step is whoever
    assigned the ticket to its current owner (Ticket.assigned_by),
    plus — only when the current owner is Staff — their own
    reporting_manager_id as a parallel recipient (deduped if it's the
    same person). If ignored, the next step climbs one more hop up the
    real assignment history (reconstructed from ticket_audit_logs,
    since Ticket.assigned_by only ever reflects the *current*
    assignment). Site Lead/Super Admin remain the one terminal,
    role-based safety net — reached only once that chain is genuinely
    exhausted (or was empty to begin with), never as a routing step in
    its own right.

    Never invents its own reshift math for the Resolution SLA clock —
    the two deliberate exceptions are _set_ticket_priority_to_critical
    and _complete_acceptance:

    - _set_ticket_priority_to_critical runs immediately in
      _create_escalation (manual_escalate/auto_escalate_if_needed) — a
      ticket's priority (and every Critical badge/filter it drives)
      becomes CRITICAL the instant it escalates, full stop. This is a
      plain Ticket.current_priority write; it never touches the
      Resolution SLA clock itself.
    - acknowledge() only stops the ack-window auto-advance
      (evaluate_overdue only considers ACTIVE escalations) — it does
      NOT reshift the Resolution SLA and does NOT advance the handling
      stage. Acknowledging alone means "someone is looking at this,"
      not "someone has taken it on."
    - _complete_acceptance (called from acknowledge_via_assignment —
      i.e. claim_ticket/transfer_agent — and from confirm_assignment)
      is the one place the handling stage actually advances and the
      Resolution SLA reshifts, once a supervisor has *also* settled who
      the ticket is assigned to. This is the "Resolution SLA starts
      only after Acknowledge AND Assign" requirement: acknowledging and
      then never assigning anyone leaves the clock parked at its
      pre-escalation target indefinitely, by design.

    Handling-stage progression (TicketEscalation.handling_stage /
    handling_stage_started_at / handling_stage_due_at) is a genuinely
    independent fact from escalation-ladder progression
    (level/status/has_advanced_past_starting_level) — this is the core
    fix of the 2026-07-20 redesign. A ladder advance caused by an
    acknowledgment-window timeout (evaluate_overdue) NEVER touches the
    handling-stage fields or reshifts the Resolution SLA; only a
    genuine accept -> assign -> (handling-stage-window-elapses) ->
    re-accept cycle does. _complete_acceptance advances the stage
    exactly once per genuinely new cycle (guarded by
    handling_stage_due_at being NULL — see that method), always
    resolving the target as original_priority's policy row's
    resolution_target_minutes x handling_stage_percentages[stage],
    never off whatever ResolutionSLA.priority happens to be — see
    _resolve_stage_target_minutes. ResolutionSLA.priority itself no
    longer gets forced to CRITICAL on acceptance; it stays at
    original_priority for the ticket's whole life, since
    ResolutionSLA.active_target_minutes (not priority) now carries the
    real target.

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
        audit_log_repository: AuditLogRepository,
        notification_service: NotificationService | None = None,
        escalation_handling_sla_service: EscalationHandlingSlaService | None = None,
    ):
        self.ticket_escalation_repository = ticket_escalation_repository
        self.ticket_repository = ticket_repository
        self.resolution_sla_repository = resolution_sla_repository
        self.sla_policy_repository = sla_policy_repository
        self.user_repository = user_repository
        # The one place the historical assignment chain (beyond
        # Ticket.assigned_by's single current-state field) is
        # reconstructed — see escalation_rules.build_chain_owner_ids.
        self.audit_log_repository = audit_log_repository
        self.notification_service = notification_service
        # Optional so existing callers/tests that construct this
        # service directly (see tests/test_escalation_service.py) keep
        # working unchanged — every call site below no-ops the
        # handling-SLA side effect when this is None, same convention
        # as notification_service above.
        self.escalation_handling_sla_service = escalation_handling_sla_service

    # ---------------------------------------------------------
    # Owner resolution — assignment-chain based, not role hierarchy.
    # See escalation_rules.build_chain_owner_ids/resolve_owners_for_chain
    # for the actual routing logic; this class only wires the two
    # together with this service's own repositories.
    # ---------------------------------------------------------

    async def _build_chain(self, ticket: Ticket) -> list[UUID]:
        return await build_chain_owner_ids(ticket, self.audit_log_repository)

    async def _resolve_step(
        self, *, ticket: Ticket, chain_owner_ids: list[UUID], chain_position: int
    ) -> tuple[EscalationLevel, dict[UUID, str]]:
        """
        Resolves one escalation step's (level, owner -> role-tag map).
        `chain_position >= len(chain_owner_ids)` means the chain is
        exhausted (or was empty to begin with) — the terminal Site
        Lead/Super Admin safety net, level=SITE_LEAD; every other
        position is level=ASSIGNMENT_CHAIN. Never a role name — see
        the class docstring.
        """

        owners = await resolve_owners_for_chain(
            ticket=ticket,
            chain_owner_ids=chain_owner_ids,
            chain_position=chain_position,
            user_repository=self.user_repository,
            resolve_site_lead_fallback_ids=lambda: resolve_global_inbox_user_ids(
                self.user_repository
            ),
        )
        level = (
            EscalationLevel.SITE_LEAD
            if chain_position >= len(chain_owner_ids)
            else EscalationLevel.ASSIGNMENT_CHAIN
        )
        if not owners:
            logger.warning(
                "Escalation for ticket %s resolved to zero owners at chain "
                "position %s (no Site Lead/Super Admin could be found either).",
                ticket.ticket_id,
                chain_position,
            )
        return level, owners

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

        # Super Admin/Site Lead see every escalation regardless of
        # which step currently owns it (Super Admin: "All
        # escalations"; Site Lead: "Escalations") — not just once the
        # chain happens to be exhausted. Reuses the same
        # already-established GLOBAL_INBOX resolver the terminal
        # SITE_LEAD fallback itself uses (`_resolve_step` above); the
        # set union means an owner who's also in this set (e.g. the
        # chain has already reached the terminal fallback) isn't
        # notified twice.
        recipient_ids = owner_ids | await resolve_global_inbox_user_ids(self.user_repository)

        if self.notification_service is not None:
            await self.notification_service.notify(
                recipient_ids,
                notification_type,
                title=title,
                message=message,
                link=f"/tickets/{ticket.ticket_id}",
                related_entity_type="ticket",
                related_entity_id=ticket.ticket_id,
            )

        await send_notification_emails(
            recipient_ids=recipient_ids,
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
        ensure_ticket_not_closed(ticket)

        existing = await self.ticket_escalation_repository.get_active_by_ticket_id(
            ticket_id
        )

        # "Current owner" is Ticket.agent_id normally — but the instant
        # an escalation is created, ownership moves to that escalation's
        # own owner_ids, and agent_id is a stale reference to the
        # *previous* owner until a supervisor actually completes
        # Acknowledge & Assign (EscalationService._complete_acceptance).
        # `existing.handling_stage_due_at` is exactly the signal that
        # tells the two apart — non-null iff acceptance has completed
        # for the current level (see _complete_acceptance's own
        # docstring; the frontend's SlaCard.tsx computes the identical
        # `isAwaitingEscalationAcceptance` flag off this same field) —
        # so while it's still null, authorization must key off owner_ids,
        # not agent_id, or the previous owner would keep the ability to
        # re-escalate a ticket they no longer own. Once acceptance has
        # completed, ownership has concretely reverted to whichever real
        # agent the ticket was assigned to (which may or may not be one
        # of owner_ids — e.g. handed straight back to the original
        # owner), so agent_id becomes authoritative again, exactly as
        # before this check existed. An unclaimed ticket with no active
        # escalation (agent_id is None) still has no current owner, so
        # nobody can manually escalate it via this check until someone
        # claims it first.
        if existing is not None and existing.handling_stage_due_at is None:
            if str(current_user.user_id) not in existing.owner_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only the ticket's current escalation owner can manually escalate it.",
                )
        elif ticket.agent_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the ticket's current owner can manually escalate it.",
            )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        if existing is None:
            resolution_clock = await self.resolution_sla_repository.get_by_ticket_id(
                ticket_id
            )

            escalation = await self._create_escalation(
                ticket=ticket,
                resolution_clock=resolution_clock,
                triggered_by=TRIGGERED_BY_MANUAL,
                triggered_by_user_id=current_user.user_id,
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

        # An escalation is already active — a manual escalation now
        # means "move it one level further along the same chain,"
        # reusing _advance_escalation_level (the exact ack-window-
        # timeout advance mechanics: owner resolution, handling-stage
        # cleanup, escalation history) rather than standing up a
        # second, parallel chain. allow_terminal_renotify=False turns
        # an already-at-SITE_LEAD ticket into a 400 instead of a
        # same-level re-notify — there's no level above SITE_LEAD to
        # manually escalate to.
        old_level = existing.level
        now = datetime.now(timezone.utc)
        result = await self._advance_escalation_level(
            escalation=existing,
            ticket=ticket,
            now=now,
            allow_terminal_renotify=False,
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This ticket has already reached the highest escalation "
                    "level and cannot be escalated further."
                ),
            )
        new_level, new_ack_due_at, updated = result

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.ESCALATION_ADVANCED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"level": old_level.value},
            new_values={
                "level": new_level.value,
                "owner_ids": updated.owner_ids,
                "triggered_by": TRIGGERED_BY_MANUAL,
            },
        )

        await self._notify_owners(
            ticket=ticket,
            owner_ids={UUID(u) for u in updated.owner_ids},
            notification_type=NotificationType.ESCALATION_ADVANCED,
            title=f"Ticket Escalated: {ticket.title}",
            message=(
                f"{current_user.name} manually escalated ticket \"{ticket.title}\" "
                f"({ticket.current_priority.value} priority) from "
                f"{old_level.value.replace('_', ' ').title()} to "
                f"{new_level.value.replace('_', ' ').title()}.\n\n"
                f"Please acknowledge by {new_ack_due_at.strftime('%Y-%m-%d %H:%M UTC')} "
                "— if this isn't acknowledged in time, it will automatically "
                "advance to the next level."
            ),
        )

        return TicketActionResponse(
            interaction_id=None,
            ticket_id=ticket_id,
            message="Ticket escalated.",
            created_at=now,
        )

    async def auto_escalate_if_needed(
        self, *, ticket: Ticket, resolution_clock: ResolutionSLA | None
    ) -> bool:
        """
        Called from SLASweepService the first time a Resolution SLA
        clock crosses ESCALATED — 100% elapsed, the sole terminal tier
        in the Resolution SLA ladder (see thresholds_reached's own
        docstring; there is no separate BREACHED tier anymore) — a
        no-op if this ticket already has an active escalation (manual
        or automatic), so a supervisor who pre-emptively escalated
        before the SLA target was reached (see the spec's own
        12:30-escalation-before-13:00-target example) never gets a
        second, redundant chain created underneath them. Returns
        whether a new escalation was actually created, so the sweep can
        tally it into SLASweepResponse.
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
                "reached 100% of its Resolution SLA target with no active escalation, "
                f"so it was automatically escalated to {escalation.level.value.replace('_', ' ').title()}.\n\n"
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

    async def _resolve_stage_target_minutes(
        self, *, original_priority: TicketPriority, stage: int
    ) -> int:
        """
        original_target_minutes x handling_stage_percentages[stage-1]
        (or the LAST configured percentage, if `stage` exceeds the
        configured list's length — repeats rather than growing
        unboundedly or erroring). Always resolved from
        `original_priority` — the escalation's own snapshotted,
        never-mutated priority-before-escalation — never from whatever
        ResolutionSLA.priority currently is; that was the exact bug
        this redesign fixes (see the class docstring). Falls back to
        DEFAULT_HANDLING_STAGE_TARGET_MINUTES only if no policy row
        exists at all for this priority, same "never let missing SLA
        config block the underlying action" convention
        _ack_target_minutes above already uses.
        """

        policy = await self.sla_policy_repository.get_by_priority(original_priority)
        if policy is None or not policy.handling_stage_percentages:
            return DEFAULT_HANDLING_STAGE_TARGET_MINUTES

        percentages = policy.handling_stage_percentages
        stage_pct = percentages[min(stage - 1, len(percentages) - 1)]
        return round(policy.resolution_target_minutes * stage_pct / 100)

    async def _create_escalation(
        self,
        *,
        ticket: Ticket,
        resolution_clock: ResolutionSLA | None,
        triggered_by: str,
        triggered_by_user_id: UUID | None,
    ) -> TicketEscalation:
        # Captured BEFORE the priority flip below — this is the
        # escalation's durable record of what the ticket's priority
        # used to be (see TicketEscalation.original_priority's own
        # docstring), and also what the Resolution SLA clock keeps
        # running against until this escalation actually advances past
        # its starting level (has_advanced_past_starting_level).
        original_priority = ticket.current_priority

        # The ticket's priority becomes CRITICAL immediately — before
        # resolving owners/ack-window below, so a freshly-escalated
        # ticket's own ack window is CRITICAL's (tighter) one right
        # away, not its previous priority's. The Resolution SLA clock
        # itself is untouched here — see
        # _reshift_sla_for_escalation_acceptance's own docstring for
        # why that part waits for acknowledge/assignment, and is now
        # additionally gated on has_advanced_past_starting_level.
        await self._set_ticket_priority_to_critical(ticket)

        now = datetime.now(timezone.utc)
        chain_owner_ids = await self._build_chain(ticket)
        level, owners = await self._resolve_step(
            ticket=ticket, chain_owner_ids=chain_owner_ids, chain_position=0
        )
        # Resolved from original_priority, not ticket.current_priority —
        # by this point the priority flip above has already set the
        # latter to CRITICAL, and the ack window (like the handling-
        # stage target in _resolve_stage_target_minutes) must always
        # follow the ticket's real, pre-escalation priority tier, never
        # CRITICAL's own policy row (see sla_service.update_policy's
        # matching guard — CRITICAL isn't an independently configurable
        # tier at all).
        ack_minutes = await self._ack_target_minutes(original_priority)

        return await self.ticket_escalation_repository.create(
            ticket_id=ticket.ticket_id,
            resolution_sla_id=(
                resolution_clock.resolution_sla_id if resolution_clock is not None else None
            ),
            level=level,
            owner_ids=set(owners.keys()),
            owner_roles=owners,
            chain_owner_ids=chain_owner_ids,
            chain_position=0,
            triggered_by=triggered_by,
            triggered_by_user_id=triggered_by_user_id,
            ack_due_at=now + timedelta(minutes=ack_minutes),
            now=now,
            original_priority=original_priority,
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
        # checks in this codebase, and deliberately no
        # ticket:acknowledge_escalation permission fallback either: that
        # permission is granted "Full" (unscoped) to Account Manager/
        # Team Lead/Site Lead/Super Admin by role default (see
        # DEFAULT_ROLES in scripts/rbac_seed/seed.py), and has_permission
        # can't distinguish a role-default grant from a genuine per-user
        # override — so treating it as an OR-bypass here would let any
        # Account Manager/Team Lead acknowledge an escalation that
        # hasn't reached their level yet, the exact bug this check
        # exists to prevent. A Site Lead/Super Admin only becomes a
        # real owner once the chain actually reaches SITE_LEAD
        # (resolve_global_inbox_user_ids populates owner_ids for them at
        # that point) — allowing them to acknowledge earlier would let
        # them jump the queue on a TEAM_LEAD/MANAGER-level escalation,
        # exactly the "escalation should happen one level at a time"
        # behavior this check exists to guarantee. Mirrors the same
        # owner_ids-only rule the Escalated tab's own visibility query
        # now enforces (TicketRepository._escalated_owner_condition).
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
        on ACTIVE, returns None otherwise), and the handling-stage
        advance below is separately guarded so a second call while the
        current stage is still running never advances the stage or
        reshifts the clock a second time.
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

        # Handling-stage advance — deliberately independent of
        # has_advanced_past_starting_level (escalation-ladder
        # movement). A genuinely new handling cycle starts here every
        # time acceptance completes, whether this is the very first
        # acceptance ever (stage 0 -> 1) or a re-acceptance after a
        # real handling-stage breach (stage N -> N+1) — an
        # acknowledgment-window timeout alone (evaluate_overdue) never
        # reaches this method, so it can never trigger this advance.
        # Guarded on handling_stage_due_at being NULL (no stage
        # currently running) so a second call for the SAME already-
        # running stage (e.g. acknowledge() then confirm_assignment()
        # both routing here) is a genuine no-op — not just an
        # idempotent re-write of the same values, a real skip.
        if updated.handling_stage_due_at is None:
            next_stage = updated.handling_stage + 1
            stage_target_minutes = await self._resolve_stage_target_minutes(
                original_priority=updated.original_priority, stage=next_stage
            )

            updated.handling_stage = next_stage
            updated.handling_stage_started_at = now
            updated.handling_stage_due_at = now + timedelta(minutes=stage_target_minutes)

            # Deferred import to avoid a circular import (sla_service.py
            # imports build_escalation_service from this module at
            # module level). ResolutionSLA.priority is passed as
            # original_priority, never CRITICAL — see ResolutionSLA's
            # own docstring for why it no longer gets forced to
            # CRITICAL on acceptance.
            from app.ticketing.services.sla_service import build_sla_service

            sla_service = build_sla_service(self.ticket_repository.db)
            await sla_service.restart_resolution_clock_for_escalation(
                ticket_id=ticket.ticket_id,
                new_priority=updated.original_priority,
                new_target_minutes=stage_target_minutes,
            )

            # Dual-write, per this session's "migrate behavior first,
            # verify nothing depends on it, remove in a later cleanup
            # phase" decision — EscalationHandlingSLA is no longer what
            # drives anything below, but it's kept populated with the
            # exact same target so nothing currently reading it (e.g.
            # sla_service.py's get_ticket_sla_state, the ticket-detail
            # "Escalation Handling SLA" card) goes stale during the
            # transition.
            if self.escalation_handling_sla_service is not None:
                await self.escalation_handling_sla_service.start_if_not_started(
                    escalation=updated,
                    ticket=ticket,
                    target_minutes=stage_target_minutes,
                )

            await self.ticket_repository.db.flush()
            await self.ticket_repository.db.refresh(updated)

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
            new_values={
                "level": escalation.level.value,
                "via": via,
                "handling_stage": updated.handling_stage,
            },
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

        # Confirming "keep the current assignee" collapses to a
        # self-assign in the rare case the Reporting Manager is
        # themselves already ticket.agent_id — barred the same as the
        # transfer_agent branch in InteractionService.
        # acknowledge_and_assign_escalation.
        if (
            ticket.agent_id == current_user.user_id
            and escalation.owner_roles.get(str(current_user.user_id))
            == OWNER_ROLE_REPORTING_MANAGER
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Reporting managers cannot assign this ticket to themselves.",
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

    async def _resolve_category_account_managers(self, ticket_type: str) -> list[User]:
        """
        Account Managers who are Reporting Managers for the ticket's own
        category (ReportingManagerTeam — see that model's own docstring
        and root CLAUDE.md's "Organization Structure" section) — the one
        real Account-Manager-to-category relationship this data model
        has. Returns [] rather than raising if the ticket's ticket_type
        string doesn't match any seeded Category (same "degrade safely"
        convention as _resolve_owners_with_fallback above), or if no AM
        is currently mapped to it.
        """

        category_repository = CategoryRepository(self.ticket_repository.db)
        categories = await category_repository.list_all()
        category = next(
            (c for c in categories if c.category_name.value == ticket_type), None
        )
        if category is None:
            return []

        reporting_manager_repository = ReportingManagerRepository(self.ticket_repository.db)
        account_manager_ids = (
            await reporting_manager_repository.list_account_manager_ids_by_category(
                category.category_id
            )
        )
        if not account_manager_ids:
            return []

        users = await self.user_repository.list_by_ids(account_manager_ids)
        return [u for u in users if u.is_active]

    async def is_valid_account_manager_target(
        self, ticket: Ticket, candidate_id: UUID
    ) -> bool:
        """
        Re-validates a submitted Account Manager id server-side against
        _resolve_category_account_managers — the exact same source
        get_acknowledge_candidates already offers the caller — rather
        than trusting the submitted id alone (same convention
        AssignmentService.resolve_target already uses), and rather than
        InteractionService.transfer_agent independently re-deriving a
        second, differently-scoped definition of "valid Account
        Manager" (it previously checked the ticket's client's own
        account_manager_id, which is a different relationship — see
        _resolve_category_account_managers' own docstring — so an
        Account Manager offered in the dropdown here could still fail
        on Confirm). Called from InteractionService.transfer_agent.
        """

        candidates = await self._resolve_category_account_managers(ticket.ticket_type)
        return any(u.user_id == candidate_id for u in candidates)

    async def get_acknowledge_candidates(
        self, ticket_id: UUID, current_user: User
    ) -> AssignableAgentsResponse:
        """
        Who the caller may hand this escalated ticket to when
        acknowledging it — every active, agent-capable user other than
        the ticket's current agent and the caller themselves, grouped
        by role. This is the exact same "existing assignment
        permissions" InteractionService.get_transfer_candidates already
        offers for an ordinary reassignment (any active, agent-capable
        user, any role/category/hierarchy — see that method's own
        docstring), reused here rather than standing up a second,
        escalation-specific candidate table. ensure_can_reassign_ticket
        is the same reason: an escalation owner who couldn't reassign
        an ordinary ticket shouldn't be shown a candidate list here they
        can't actually act on either.

        The caller's own "assign to myself" option is the separate `me`
        field, never included in `groups` — and is omitted entirely
        (`me=None`) when the caller's own owner_roles tag for this
        escalation is OWNER_ROLE_REPORTING_MANAGER: a Reporting Manager
        may Acknowledge + Assign to someone else, but never to
        themselves (root CLAUDE.md's "SLA & Escalation" section, Rule
        4/Flow E). Every other tagged owner (OWNER_ROLE_ASSIGNEE_CHAIN/
        _SITE_LEAD_FALLBACK) keeps full existing permissions, including
        self-assign — see InteractionService.
        acknowledge_and_assign_escalation for the matching, non-
        bypassable backend enforcement of this same rule.
        """

        ticket = await self.ticket_repository.get_by_id(ticket_id)
        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found."
            )
        ensure_agent_can_view_ticket(ticket, current_user)
        ensure_can_reassign_ticket(current_user)

        escalation = await self.ticket_escalation_repository.get_active_by_ticket_id(
            ticket_id
        )

        current_agent_id = ticket.agent_id
        by_role: dict[str, list[User]] = {
            role_name: []
            for role_name in (
                STAFF_ROLE_NAME,
                TEAM_LEAD_ROLE_NAME,
                ACCOUNT_MANAGER_ROLE_NAME,
                SITE_LEAD_ROLE_NAME,
                SUPER_ADMIN_ROLE_NAME,
            )
        }
        for user in await self.user_repository.list_all_active():
            role_name = user.role.name if user.role is not None else None
            if role_name not in AGENT_ROLE_NAMES:
                continue
            if user.user_id in (current_agent_id, current_user.user_id):
                continue
            by_role[role_name].append(user)

        groups = [
            _to_assignable_group(role_name, users)
            for role_name, users in by_role.items()
            if users
        ]

        is_reporting_manager = (
            escalation is not None
            and escalation.owner_roles.get(str(current_user.user_id))
            == OWNER_ROLE_REPORTING_MANAGER
        )

        return AssignableAgentsResponse(
            me=(
                None
                if is_reporting_manager
                else AssignableUserSummary(
                    user_id=current_user.user_id,
                    name=current_user.name,
                    employee_number=current_user.employee_number,
                    is_on_leave=current_user.is_on_leave,
                )
            ),
            groups=groups,
        )

    # ---------------------------------------------------------
    # Shared advance mechanics — the one place an escalation actually
    # moves to the next level in the chain, used by both the
    # ack-window-timeout trigger (evaluate_overdue below) and the
    # manual trigger (manual_escalate's re-escalate branch above), so
    # owner resolution / SLA handling-stage cleanup / escalation
    # history can never diverge between the two triggers — only what
    # caused the advance and how it's announced differs per caller.
    # ---------------------------------------------------------

    async def _advance_escalation_level(
        self,
        *,
        escalation: TicketEscalation,
        ticket: Ticket,
        now: datetime,
        allow_terminal_renotify: bool,
    ) -> tuple[EscalationLevel, datetime, TicketEscalation] | None:
        """
        Returns None when there's nothing to do: either another process
        already changed this escalation's level since it was read
        (advance()'s own optimistic-concurrency guard lost the race),
        or the chain is already at its terminal SITE_LEAD level and the
        caller doesn't want a same-level re-notify
        (allow_terminal_renotify=False — manual_escalate's case, since
        a manual re-escalate at the terminal level should be rejected
        outright rather than silently re-pinging the same owners).
        evaluate_overdue passes True, preserving its own pre-existing
        "re-notify at terminal" behavior.

        On success, returns (new_level, new_ack_due_at, updated) — the
        caller already has the pre-advance level (it's whatever
        `escalation.level` was before calling this), so that's not
        returned again here.
        """

        # Stored as strings (JSONB) — converted back to UUID so the
        # dict-key identity checks in resolve_owners_for_chain (e.g. the
        # Reporting-Manager dedup) compare like with like against
        # User.reporting_manager_id, a real UUID.
        chain_owner_ids = [UUID(s) for s in escalation.chain_owner_ids]

        already_terminal = escalation.chain_position >= len(chain_owner_ids)
        if already_terminal and not allow_terminal_renotify:
            return None
        target_position = (
            escalation.chain_position if already_terminal else escalation.chain_position + 1
        )

        new_level, owners = await self._resolve_step(
            ticket=ticket,
            chain_owner_ids=chain_owner_ids,
            chain_position=target_position,
        )
        # original_priority, not ticket.current_priority — see
        # _create_escalation's matching comment. The ticket has already
        # been CRITICAL since its first escalation, so
        # ticket.current_priority is never the right input here.
        ack_minutes = await self._ack_target_minutes(escalation.original_priority)
        new_ack_due_at = now + timedelta(minutes=ack_minutes)

        # A handling stage running at the level being left behind no
        # longer means anything once ownership moves again — cleared
        # the same way advance_for_handling_sla_breach already clears
        # it, so the sweep never later evaluates a breach against a
        # window this advance has already superseded. A no-op for the
        # ack-window-timeout path, which never reaches this with a
        # stage active (a stage only ever starts once ACKNOWLEDGED, and
        # evaluate_overdue only ever considers still-ACTIVE
        # escalations).
        escalation.handling_stage_due_at = None

        updated = await self.ticket_escalation_repository.advance(
            escalation,
            new_level=new_level,
            owner_ids=set(owners.keys()),
            owner_roles=owners,
            chain_position=target_position,
            ack_due_at=new_ack_due_at,
            now=now,
        )
        if updated is None:
            return None

        return new_level, new_ack_due_at, updated

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

        Each escalation is processed in its own SAVEPOINT
        (db.begin_nested()) so one escalation's failure can't roll back
        another's — or the rest of the sweep tick's already-flushed
        work — same isolation pattern SLASweepService's own per-clock
        loops already use.
        """

        overdue = await self.ticket_escalation_repository.list_overdue_active(now=now)
        advanced = 0
        db = self.ticket_repository.db

        for escalation in overdue:
            try:
                async with db.begin_nested():
                    ticket = await self.ticket_repository.get_by_id(escalation.ticket_id)
                    if ticket is None:
                        continue

                    old_level = escalation.level
                    result = await self._advance_escalation_level(
                        escalation=escalation,
                        ticket=ticket,
                        now=now,
                        allow_terminal_renotify=True,
                    )
                    if result is None:
                        # Lost the race — another process (e.g. an
                        # overlapping sweep on a second backend
                        # instance) already advanced this escalation
                        # since list_overdue_active read it. Nothing
                        # left to do for this one.
                        continue
                    new_level, new_ack_due_at, updated = result
                    owner_ids = {UUID(u) for u in updated.owner_ids}
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
                        new_values={
                            "level": new_level.value,
                            "owner_ids": [str(u) for u in owner_ids],
                        },
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
            except Exception:
                logger.warning(
                    "Escalation sweep: failed advancing overdue escalation %s (ticket %s)",
                    escalation.escalation_id,
                    escalation.ticket_id,
                    exc_info=True,
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

        # Clear the elapsed stage's window — handling_stage itself is
        # left as-is (the next successful _complete_acceptance is what
        # advances it), but handling_stage_due_at being non-null is
        # what list_handling_stage_overdue's idempotency relies on, so
        # this must happen exactly once per real breach. Included in
        # the same flush as the advance() call below (both mutate the
        # same `escalation` object before either is written).
        escalation.handling_stage_due_at = None

        # Deliberately NOT just climbing to the next chain position —
        # unlike evaluate_overdue's ack-window-lapse case above (where
        # the current owner never even acknowledged it, so genuinely
        # climbing one hop further is correct), a handling-SLA breach
        # means someone DID accept and settle ownership, and it's THAT
        # assignee who then failed to resolve it in time. That's a
        # fresh failure against the ticket's now-different current
        # ownership (agent_id/assigned_by both changed the moment
        # acceptance completed), not evidence the current chain itself
        # is unreachable — so this rebuilds the chain fresh, the exact
        # same way a brand-new escalation would, and resets
        # chain_position back to 0 against it. For the common case —
        # Team Lead accepted and handed the ticket back to Staff, and
        # Staff then missed the handling window — this correctly lands
        # back on the Team Lead again (their own assigned_by-derived
        # chain position 0), instead of jumping straight past them.
        new_chain_owner_ids = await self._build_chain(ticket)
        new_level, owners = await self._resolve_step(
            ticket=ticket, chain_owner_ids=new_chain_owner_ids, chain_position=0
        )
        # original_priority, not ticket.current_priority — see
        # _create_escalation's matching comment.
        ack_minutes = await self._ack_target_minutes(escalation.original_priority)
        new_ack_due_at = now + timedelta(minutes=ack_minutes)

        updated = await self.ticket_escalation_repository.advance(
            escalation,
            new_level=new_level,
            owner_ids=set(owners.keys()),
            owner_roles=owners,
            chain_owner_ids=new_chain_owner_ids,
            chain_position=0,
            ack_due_at=new_ack_due_at,
            now=now,
        )
        if updated is None:
            # Lost the race — another process already advanced this
            # escalation since it was read. Nothing left to do.
            return False

        owner_ids = set(owners.keys())
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
            handling_stage=escalation.handling_stage,
            handling_stage_started_at=escalation.handling_stage_started_at,
            handling_stage_due_at=escalation.handling_stage_due_at,
            original_priority=escalation.original_priority,
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
        audit_log_repository=AuditLogRepository(db),
        notification_service=notification_service,
        escalation_handling_sla_service=build_escalation_handling_sla_service(db),
    )

"""
Multi-user / multi-category ticket assignment — the ONE place that
mutates ticket_assignments / ticket_categories / ticket_assignment_slas
and keeps the legacy single-value projections on `tickets` in sync:

    tickets.agent_id / assigned_by  <- the active PRIMARY assignment
    tickets.ticket_type             <- the PRIMARY ticket category's name
    tickets.current_status          <- driven by the primary assignment
                                       (see InteractionService.change_status)

Semantics (see TicketAssignment's docstring):

- PRIMARY vs SECONDARY is accountability only (escalation follows the
  primary). It never grants or denies an action — RBAC
  (access_control.ensure_agent_can_act_on_ticket) stays authoritative,
  and treats every active assignee identically.
- Every assignment status except CLOSED is individual. CLOSED is only
  written by the universal close (`close_all_for_ticket`), which closes
  every active assignment and completes every live SLA run atomically.
- Every explicitly assigned user gets their own Resolution SLA run.
  Categories never get one.

Existing single-assignee entry points (claim/transfer/create-from-
inbox/close/reopen/status change) keep their own validation, audit and
notification behavior byte-for-byte and call the `on_*` hooks here for
the assignment-table side; the new multi-assignment API calls the
`add_users` / `remove_assignment` / `change_primary` / category methods.
Nothing here commits — the request's get_db() commits once.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.notifications.service import NotificationService, NotificationType
from app.ticketing.enums import (
    AuditEntityType,
    AuditEventType,
    SLAClockStatus,
    TicketPriority,
    TicketStatus,
)
from app.ticketing.models.ticket import Ticket
from app.ticketing.models.ticket_assignment import TicketAssignment
from app.ticketing.models.ticket_assignment_sla import TicketAssignmentSLA
from app.ticketing.models.ticket_category import TicketCategory
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.resolution_sla_repository import (
    compute_reshifted_due_at,
    compute_resumed_due_at,
)
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_assignment_repository import (
    TicketAssignmentRepository,
)
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.access_control import (
    ACCOUNT_MANAGER_ROLE_NAME,
    AGENT_ROLE_NAMES,
    CATEGORY_SCOPED_ROLE_NAMES,
    SUPERVISOR_ROLE_NAMES,
    ensure_account_manager_owns_ticket_client,
    ensure_agent_can_view_ticket,
    ensure_can_assign_unowned_ticket,
    ensure_can_reassign_ticket,
    ensure_has_permission,
    ensure_ticket_not_closed,
    has_permission_for_ticket,
    resolve_status_after_assignment,
)
from app.ticketing.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)

# completion_reason values for TicketAssignmentSLA.
COMPLETION_RESOLVED = "RESOLVED"
COMPLETION_TICKET_CLOSED = "TICKET_CLOSED"
COMPLETION_UNASSIGNED = "UNASSIGNED"

_INACTIVE_ASSIGNMENT_STATUSES = (TicketStatus.RESOLVED, TicketStatus.CLOSED)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=detail)


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=detail)


@dataclass
class AssignmentSnapshot:
    """Plain, audit-friendly view of one assignment's state."""

    assignment_id: UUID
    user_id: UUID
    is_primary: bool
    status: TicketStatus

    def as_audit(self) -> dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "user_id": self.user_id,
            "is_primary": self.is_primary,
            "status": self.status,
        }


def snapshot(assignment: TicketAssignment) -> AssignmentSnapshot:
    return AssignmentSnapshot(
        assignment_id=assignment.assignment_id,
        user_id=assignment.user_id,
        is_primary=assignment.is_primary,
        status=assignment.status,
    )


# =============================================================
# Per-assignment Resolution SLA runs
# =============================================================


class AssignmentSLAEngine:
    """
    Same clock rules as the ticket-level ResolutionSLA (and the same
    pure due_at math — compute_resumed_due_at/compute_reshifted_due_at),
    applied to one assignment's own run. Differences, by design:

    - A reopen (leaving RESOLVED, or a reopened ticket) starts a NEW
      run (run_number + 1) instead of resetting the old row in place,
      so earlier breaches/completions stay as history.
    - Escalation handling-stage restarts are ticket-level only and do
      not touch assignment runs (escalation follows the primary's
      ticket-level clock).
    """

    def __init__(
        self,
        repository: TicketAssignmentRepository,
        sla_policy_repository: SLAPolicyRepository,
    ):
        self.repository = repository
        self.sla_policy_repository = sla_policy_repository

    async def _target_minutes(self, priority: TicketPriority) -> int | None:
        policy = await self.sla_policy_repository.get_by_priority(priority)
        if policy is None:
            # Same "missing SLA config never blocks the business action"
            # rule SLAService._get_policy follows.
            logger.warning("No SLAPolicy for priority %s — skipping assignment SLA.", priority)
            return None
        return policy.resolution_target_minutes

    async def start_run(
        self,
        assignment: TicketAssignment,
        *,
        priority: TicketPriority,
        paused: bool = False,
        now: datetime | None = None,
    ) -> TicketAssignmentSLA | None:
        """
        Idempotent: returns the existing live run unchanged if one
        exists — so re-assigning, changing primary, or a racing
        request can never create a second timer (the partial unique
        index uq_ticket_assignment_slas_one_live_run backs this up).
        """

        live = await self.repository.get_live_run(assignment.assignment_id)
        if live is not None:
            return live

        target = await self._target_minutes(priority)
        if target is None:
            return None

        now = now or _now()
        run = TicketAssignmentSLA(
            assignment_id=assignment.assignment_id,
            ticket_id=assignment.ticket_id,
            user_id=assignment.user_id,
            run_number=await self.repository.next_run_number(assignment.assignment_id),
            priority=priority,
            status=SLAClockStatus.PAUSED if paused else SLAClockStatus.RUNNING,
            started_at=now,
            due_at=now + timedelta(minutes=target),
            active_target_minutes=target,
            paused_at=now if paused else None,
            total_paused_seconds=0,
        )
        return await self.repository.add_run(run)

    async def pause(self, assignment: TicketAssignment, *, now: datetime | None = None) -> None:
        run = await self.repository.get_live_run(assignment.assignment_id)
        if run is None or run.status != SLAClockStatus.RUNNING:
            return
        run.status = SLAClockStatus.PAUSED
        run.paused_at = now or _now()
        await self.repository.flush()

    @staticmethod
    def _resume_run(run: TicketAssignmentSLA, now: datetime) -> None:
        if run.status != SLAClockStatus.PAUSED or run.paused_at is None:
            return
        run.due_at = compute_resumed_due_at(run.due_at, run.paused_at, now)
        run.total_paused_seconds += int((now - run.paused_at).total_seconds())
        run.paused_at = None
        run.status = SLAClockStatus.RUNNING

    async def resume(self, assignment: TicketAssignment, *, now: datetime | None = None) -> None:
        run = await self.repository.get_live_run(assignment.assignment_id)
        if run is None:
            return
        self._resume_run(run, now or _now())
        await self.repository.flush()

    @staticmethod
    def _complete_run(run: TicketAssignmentSLA, now: datetime, reason: str) -> None:
        if run.status == SLAClockStatus.PAUSED and run.paused_at is not None:
            # Close out the open pause first so total_paused_seconds is
            # accurate history — same as ResolutionSLARepository.complete.
            run.total_paused_seconds += int((now - run.paused_at).total_seconds())
            run.paused_at = None
        if run.breached_at is None and run.due_at < now and run.status == SLAClockStatus.RUNNING:
            run.breached_at = run.due_at
        run.status = SLAClockStatus.COMPLETED
        run.completed_at = now
        run.completion_reason = reason

    async def complete(
        self, assignment: TicketAssignment, *, reason: str, now: datetime | None = None
    ) -> None:
        run = await self.repository.get_live_run(assignment.assignment_id)
        if run is None:
            return
        self._complete_run(run, now or _now(), reason)
        await self.repository.flush()

    async def complete_all_for_ticket(
        self, ticket_id: UUID, *, reason: str, now: datetime | None = None
    ) -> int:
        now = now or _now()
        runs = await self.repository.list_live_runs_for_ticket(ticket_id)
        for run in runs:
            self._complete_run(run, now, reason)
        await self.repository.flush()
        return len(runs)

    async def resume_all_for_ticket(self, ticket_id: UUID, *, now: datetime | None = None) -> None:
        """Customer reply landed — mirrors SLAService.resume_resolution_clock."""

        now = now or _now()
        for run in await self.repository.list_live_runs_for_ticket(ticket_id):
            self._resume_run(run, now)
        await self.repository.flush()

    async def reshift_all_for_priority(
        self, ticket_id: UUID, *, new_priority: TicketPriority, now: datetime | None = None
    ) -> None:
        """Mirrors SLAService.reshift_resolution_clock_for_priority_change."""

        target = await self._target_minutes(new_priority)
        if target is None:
            return
        now = now or _now()
        for run in await self.repository.list_live_runs_for_ticket(ticket_id):
            run.due_at = compute_reshifted_due_at(
                started_at=run.started_at,
                total_paused_seconds=run.total_paused_seconds,
                new_target_minutes=target,
                now=now,
            )
            run.priority = new_priority
            run.active_target_minutes = target
        await self.repository.flush()

    async def apply_status_transition(
        self,
        assignment: TicketAssignment,
        *,
        old_status: TicketStatus,
        new_status: TicketStatus,
        priority: TicketPriority,
    ) -> None:
        """
        The individual-status counterpart of change_status's ticket-
        level SLA block — identical rules, scoped to one assignment:
        WAITING_FOR_CLIENT pauses, leaving it resumes, entering
        RESOLVED completes, leaving RESOLVED starts a new run.
        PENDING/IN_PROGRESS/OPEN have no clock effect (as today).
        """

        if old_status == new_status:
            return
        now = _now()

        if new_status == TicketStatus.WAITING_FOR_CLIENT:
            await self.pause(assignment, now=now)
        elif old_status == TicketStatus.WAITING_FOR_CLIENT:
            await self.resume(assignment, now=now)

        if new_status == TicketStatus.RESOLVED:
            await self.complete(assignment, reason=COMPLETION_RESOLVED, now=now)
        elif old_status == TicketStatus.RESOLVED:
            await self.start_run(
                assignment,
                priority=priority,
                paused=new_status == TicketStatus.WAITING_FOR_CLIENT,
                now=now,
            )


# =============================================================
# Service
# =============================================================


class TicketAssignmentService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        notification_service: NotificationService | None = None,
        escalation_service=None,
    ):
        self.db = db
        self.repository = TicketAssignmentRepository(db)
        self.user_repository = UserRepository(db)
        self.client_repository = ClientRepository(db)
        self.sla = AssignmentSLAEngine(self.repository, SLAPolicyRepository(db))
        self.notification_service = notification_service
        self.escalation_service = escalation_service

    # ---------------------------------------------------------
    # Reads
    # ---------------------------------------------------------

    async def hydrate(self, tickets: list[Ticket]) -> None:
        await self.repository.hydrate_access_context(tickets)

    async def list_assignments(self, ticket_id: UUID) -> list[TicketAssignment]:
        return await self.repository.list_active(ticket_id)

    async def get_active_for_user(self, ticket_id: UUID, user_id: UUID) -> TicketAssignment | None:
        return await self.repository.get_active_for_user(ticket_id, user_id)

    async def get_primary(self, ticket_id: UUID) -> TicketAssignment | None:
        return await self.repository.get_active_primary(ticket_id)

    async def get_assignment_on_ticket(
        self, ticket_id: UUID, assignment_id: UUID
    ) -> TicketAssignment:
        """IDOR guard — an assignment id only resolves on its own ticket."""

        assignment = await self.repository.get(assignment_id)
        if (
            assignment is None
            or assignment.ticket_id != ticket_id
            or assignment.removed_at is not None
        ):
            raise _not_found("Assignment not found on this ticket.")
        return assignment

    # ---------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------

    async def _lock_ticket(self, ticket_id: UUID) -> Ticket:
        ticket = await self.repository.lock_ticket(ticket_id)
        if ticket is None:
            raise _not_found("Ticket not found.")
        await self.hydrate([ticket])
        return ticket

    async def _audit(
        self,
        ticket_id: UUID,
        event_type: AuditEventType,
        actor: User | None,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
    ) -> None:
        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(actor)
        await AuditLogService.log_event(
            self.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=event_type,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values=old_values,
            new_values=new_values,
        )

    async def _notify(self, user_ids, title: str, ticket: Ticket) -> None:
        if self.notification_service is None or not user_ids:
            return
        await self.notification_service.notify(
            user_ids,
            NotificationType.TICKET_ASSIGNED,
            title=title,
            message=f"Ticket TKT-{ticket.ticket_number:02d}: {ticket.title}",
            link=f"/tickets/{ticket.ticket_id}",
            related_entity_type="ticket",
            related_entity_id=ticket.ticket_id,
        )

    async def _ticket_category_names(self, ticket: Ticket) -> set[str]:
        names = getattr(ticket, "category_names", None)
        if names is None:
            await self.hydrate([ticket])
            names = ticket.category_names
        return set(names)

    async def _ensure_user_eligible(self, ticket: Ticket, user: User | None) -> User:
        """
        Target validation — never trusts the frontend. A user may be
        assigned only if they are an active agent-role user AND existing
        RBAC visibility already lets them see this ticket:
        Team Lead/Staff need a category overlap with the ticket's
        categories; an Account Manager must own the ticket's client.
        This is what keeps assignment from ever becoming an RBAC bypass
        — an assignee's visibility comes from RBAC, never from the
        assignment row. Same "any active agent role" acceptance rule as
        InteractionService.transfer_agent (an explicit product decision),
        narrowed by that visibility check.
        """

        if (
            user is None
            or not user.is_active
            or user.role is None
            or user.role.name not in AGENT_ROLE_NAMES
        ):
            raise _bad_request("Every assigned user must be an active platform user.")

        role_name = user.role.name
        if role_name in CATEGORY_SCOPED_ROLE_NAMES:
            user_categories = {c.category_name for c in (user.categories or [])}
            if not user_categories & await self._ticket_category_names(ticket):
                raise _bad_request(
                    f"{user.name} does not belong to any of this ticket's categories."
                )
        elif role_name == ACCOUNT_MANAGER_ROLE_NAME and ticket.client_company_id is not None:
            owned = await self.client_repository.list_client_ids_by_account_manager(user.user_id)
            if ticket.client_company_id not in set(owned):
                raise _bad_request(f"{user.name} is not the Account Manager for this ticket's client.")
        return user

    async def _ensure_can_manage(self, ticket: Ticket, actor: User) -> None:
        ensure_ticket_not_closed(ticket)
        ensure_agent_can_view_ticket(ticket, actor)
        await ensure_account_manager_owns_ticket_client(ticket, actor, self.client_repository)

    async def _set_primary_projection(
        self, ticket: Ticket, primary: TicketAssignment | None, actor_id: UUID | None
    ) -> None:
        ticket.agent_id = primary.user_id if primary is not None else None
        ticket.assigned_by = actor_id if primary is not None else None
        await self.repository.flush()

    async def _unset_primary(self, assignment: TicketAssignment) -> None:
        assignment.is_primary = False
        # Flush before any other row becomes primary — the partial unique
        # index allows only one active primary at any instant.
        await self.repository.flush()

    async def _new_assignment(
        self,
        ticket: Ticket,
        user_id: UUID,
        *,
        is_primary: bool,
        status: TicketStatus,
        actor_id: UUID | None,
    ) -> TicketAssignment:
        now = _now()
        assignment = TicketAssignment(
            ticket_id=ticket.ticket_id,
            user_id=user_id,
            is_primary=is_primary,
            status=status,
            assigned_by=actor_id,
            assigned_at=now,
            status_changed_at=now,
        )
        await self.repository.add(assignment)
        if status not in _INACTIVE_ASSIGNMENT_STATUSES:
            await self.sla.start_run(
                assignment,
                priority=ticket.current_priority,
                paused=status == TicketStatus.WAITING_FOR_CLIENT,
                now=now,
            )
        return assignment

    async def _soft_remove(self, assignment: TicketAssignment, actor_id: UUID | None) -> None:
        now = _now()
        await self.sla.complete(assignment, reason=COMPLETION_UNASSIGNED, now=now)
        assignment.is_primary = False
        assignment.removed_at = now
        assignment.removed_by = actor_id
        await self.repository.flush()

    # ---------------------------------------------------------
    # Legacy-entry-point hooks (claim / transfer / create / status)
    # ---------------------------------------------------------

    async def on_primary_set(
        self,
        ticket: Ticket,
        *,
        new_user_id: UUID,
        actor_id: UUID | None,
        keep_previous_as_secondary: bool = False,
    ) -> TicketAssignment:
        """
        Called AFTER an existing single-assignee flow (claim,
        transfer_agent, create-with-assignee) has already validated
        and written tickets.agent_id — projects that into the
        assignment table. Default (transfer semantics, unchanged): the
        previous primary is removed. If the new user was already a
        secondary, they are promoted in place (their own status and
        their existing SLA run are kept — no duplicate timer).
        """

        current_primary = await self.repository.get_active_primary(ticket.ticket_id)
        if current_primary is not None and current_primary.user_id == new_user_id:
            return current_primary

        if current_primary is not None:
            if keep_previous_as_secondary:
                await self._unset_primary(current_primary)
            else:
                await self._soft_remove(current_primary, actor_id)

        existing = await self.repository.get_active_for_user(ticket.ticket_id, new_user_id)
        if existing is not None:
            existing.is_primary = True
            await self.repository.flush()
            return existing

        return await self._new_assignment(
            ticket,
            new_user_id,
            is_primary=True,
            status=ticket.current_status,
            actor_id=actor_id,
        )

    async def on_ticket_created(self, ticket: Ticket, *, actor_id: UUID | None) -> None:
        """New ticket: primary category from ticket_type, primary assignee from agent_id."""

        await self.sync_primary_category(ticket, ticket.ticket_type, actor_id=actor_id)
        if ticket.agent_id is not None:
            await self.on_primary_set(ticket, new_user_id=ticket.agent_id, actor_id=actor_id)

    async def on_primary_status_changed(
        self, ticket: Ticket, *, old_status: TicketStatus, new_status: TicketStatus
    ) -> None:
        """
        change_status on the primary / ticket level: mirror the ticket's
        new status onto the primary assignment and drive its run.
        Secondaries are untouched.
        """

        primary = await self.repository.get_active_primary(ticket.ticket_id)
        if primary is None:
            return
        assignment_old = primary.status
        primary.status = new_status
        primary.status_changed_at = _now()
        await self.repository.flush()
        await self.sla.apply_status_transition(
            primary,
            old_status=assignment_old,
            new_status=new_status,
            priority=ticket.current_priority,
        )

    async def change_secondary_status(
        self,
        ticket: Ticket,
        assignment: TicketAssignment,
        new_status: TicketStatus,
        actor: User,
    ) -> None:
        """
        A non-primary assignment's own status — touches ONLY this row
        and its SLA run. The caller (InteractionService.change_status)
        has already run the usual act-on-ticket/ticket:update_status
        gates; this adds the one extra rule for acting on someone
        else's assignment.
        """

        if new_status == TicketStatus.CLOSED:
            raise _bad_request(
                "Closing a ticket must be done via the Close Ticket action, not a status change."
            )
        self.ensure_can_change_assignment_status(ticket, assignment, actor)

        old_status = assignment.status
        if old_status == new_status:
            return
        assignment.status = new_status
        assignment.status_changed_at = _now()
        await self.repository.flush()
        await self.sla.apply_status_transition(
            assignment,
            old_status=old_status,
            new_status=new_status,
            priority=ticket.current_priority,
        )
        user = await self.user_repository.get_by_id(assignment.user_id)
        await self._audit(
            ticket.ticket_id,
            AuditEventType.ASSIGNMENT_STATUS_CHANGED,
            actor,
            old_values={"assignment_id": assignment.assignment_id, "status": old_status},
            new_values={
                "assignment_id": assignment.assignment_id,
                "user_id": assignment.user_id,
                "user_name": user.name if user else None,
                "status": new_status,
            },
        )

    @staticmethod
    def ensure_can_change_assignment_status(
        ticket: Ticket, assignment: TicketAssignment, actor: User
    ) -> None:
        """
        Your own assignment: allowed (subject to the caller's RBAC
        gates). Someone else's: supervisor role or ticket:editother_ticket
        (global or scoped to this ticket) — never inferred from being
        primary.
        """

        if assignment.user_id == actor.user_id:
            return
        if actor.role.name in SUPERVISOR_ROLE_NAMES:
            return
        if has_permission_for_ticket(actor, "ticket:editother_ticket", ticket.ticket_id):
            return
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="You can only change your own assignment's status.",
        )

    async def on_priority_changed(self, ticket: Ticket, *, new_priority: TicketPriority) -> None:
        await self.sla.reshift_all_for_priority(ticket.ticket_id, new_priority=new_priority)

    async def on_customer_reply(self, ticket_id: UUID) -> None:
        await self.sla.resume_all_for_ticket(ticket_id)

    # ---------------------------------------------------------
    # Universal close / reopen
    # ---------------------------------------------------------

    async def lock_for_close(self, ticket_id: UUID) -> Ticket:
        """
        Row-locks the ticket before close_ticket's own checks run, so
        two concurrent closes serialize: the second one re-reads
        CLOSED under the lock and gets the existing "already closed"
        400 instead of double-closing.
        """

        return await self._lock_ticket(ticket_id)

    async def snapshot_active(self, ticket_id: UUID) -> list[AssignmentSnapshot]:
        return [snapshot(a) for a in await self.repository.list_active(ticket_id)]

    async def close_all_for_ticket(
        self, ticket: Ticket, *, closed_at: datetime, closed_by: UUID | None
    ) -> None:
        """
        Universal close (assignment side): every active assignment ->
        CLOSED, every live run -> COMPLETED(TICKET_CLOSED). Runs inside
        close_ticket's transaction, under its row lock — never a
        partial state where the ticket is CLOSED and an assignment or
        timer is still active.
        """

        await self.repository.close_all_active(
            ticket.ticket_id, closed_at=closed_at, closed_by=closed_by
        )
        await self.sla.complete_all_for_ticket(
            ticket.ticket_id, reason=COMPLETION_TICKET_CLOSED, now=closed_at
        )

    async def reopen_all_for_ticket(self, ticket: Ticket) -> None:
        """
        Reopen (assignment side): every active (non-removed) assignment
        returns to OPEN and starts a NEW SLA run — earlier runs stay
        COMPLETED as history. The primary is unchanged; removed users
        are not brought back.
        """

        now = _now()
        for assignment in await self.repository.list_active(ticket.ticket_id):
            assignment.status = TicketStatus.OPEN
            assignment.status_changed_at = now
            assignment.closed_at = None
            assignment.closed_by = None
            await self.repository.flush()
            await self.sla.start_run(assignment, priority=ticket.current_priority, now=now)

    # ---------------------------------------------------------
    # New multi-assignment operations
    # ---------------------------------------------------------

    async def add_users(
        self,
        ticket_id: UUID,
        user_ids: list[UUID],
        actor: User,
        *,
        primary_user_id: UUID | None = None,
    ) -> list[TicketAssignment]:
        """
        Assign one or many users in one transaction — all-or-nothing:
        every user is validated before anything is written, and any
        invalid/duplicate user rejects the whole request.
        """

        unique_ids = list(dict.fromkeys(user_ids))
        if not unique_ids:
            raise _bad_request("Select at least one user to assign.")
        if len(unique_ids) != len(user_ids):
            raise _bad_request("The same user was selected more than once.")

        ticket = await self._lock_ticket(ticket_id)
        await self._ensure_can_manage(ticket, actor)
        ensure_has_permission(actor, "ticket:assign")

        active = await self.repository.list_active(ticket_id)
        active_by_user = {a.user_id: a for a in active}
        current_primary = next((a for a in active if a.is_primary), None)

        duplicates = [uid for uid in unique_ids if uid in active_by_user]
        if duplicates:
            raise _conflict("One or more selected users are already assigned to this ticket.")

        if primary_user_id is not None and primary_user_id not in unique_ids and primary_user_id not in active_by_user:
            raise _bad_request("The primary user must be one of the assigned users.")

        # Choosing a primary on a ticket that already has a different
        # one is a reassignment of accountability — same gate as
        # transfer_agent's reassign case.
        will_change_primary = (
            primary_user_id is not None
            and current_primary is not None
            and current_primary.user_id != primary_user_id
        )
        if current_primary is None:
            ensure_can_assign_unowned_ticket(actor)
            if primary_user_id is None:
                primary_user_id = unique_ids[0]
        elif will_change_primary:
            ensure_can_reassign_ticket(actor)

        users = []
        for uid in unique_ids:
            users.append(await self._ensure_user_eligible(ticket, await self.user_repository.get_by_id(uid)))

        created: list[TicketAssignment] = []
        actor_id = actor.user_id
        old_agent_id = ticket.agent_id
        old_status = ticket.current_status

        if will_change_primary:
            await self._unset_primary(current_primary)

        primary_changed = False
        for user in users:
            is_primary = user.user_id == primary_user_id
            if is_primary:
                # Same OPEN -> IN_PROGRESS rule the single-assignee
                # flows apply when a ticket first gets an owner.
                new_ticket_status = resolve_status_after_assignment(ticket.current_status)
                if new_ticket_status is not None:
                    ticket.current_status = new_ticket_status
                status = ticket.current_status
                primary_changed = True
            else:
                status = TicketStatus.OPEN
            assignment = await self._new_assignment(
                ticket, user.user_id, is_primary=is_primary, status=status, actor_id=actor_id
            )
            created.append(assignment)
            await self._audit(
                ticket_id,
                AuditEventType.USER_ASSIGNED,
                actor,
                new_values={
                    "assignment_id": assignment.assignment_id,
                    "user_id": user.user_id,
                    "user_name": user.name,
                    "is_primary": is_primary,
                    "status": status,
                },
            )

        if primary_user_id in active_by_user and not active_by_user[primary_user_id].is_primary:
            promoted = active_by_user[primary_user_id]
            promoted.is_primary = True
            await self.repository.flush()
            primary_changed = True

        if primary_changed:
            new_primary = await self.repository.get_active_primary(ticket_id)
            await self._set_primary_projection(ticket, new_primary, actor_id)
            primary_user = await self.user_repository.get_by_id(new_primary.user_id)
            old_values: dict[str, Any] = {"agent_id": old_agent_id}
            new_values: dict[str, Any] = {
                "agent_id": new_primary.user_id,
                "agent_name": primary_user.name if primary_user else None,
            }
            if ticket.current_status != old_status:
                old_values["current_status"] = old_status
                new_values["current_status"] = ticket.current_status
            await self._audit(ticket_id, AuditEventType.PRIMARY_CHANGED, actor, old_values, new_values)
            if self.escalation_service is not None:
                await self.escalation_service.acknowledge_via_assignment(ticket_id, actor)

        await self._notify(
            {a.user_id for a in created} - {actor_id},
            "A ticket was assigned to you",
            ticket,
        )
        return created

    async def change_primary(
        self, ticket_id: UUID, assignment_id: UUID, actor: User
    ) -> TicketAssignment:
        """
        Promote an existing assignee to primary. The previous primary
        stays assigned as a secondary. Statuses and SLA runs of every
        assignee are untouched — no restart, no duplicate timer.
        """

        ticket = await self._lock_ticket(ticket_id)
        await self._ensure_can_manage(ticket, actor)
        ensure_can_reassign_ticket(actor)
        target = await self.get_assignment_on_ticket(ticket_id, assignment_id)
        if target.is_primary:
            raise _bad_request("This user is already the primary assignee.")

        current_primary = await self.repository.get_active_primary(ticket_id)
        old_agent_id = current_primary.user_id if current_primary else None
        if current_primary is not None:
            await self._unset_primary(current_primary)
        target.is_primary = True
        await self.repository.flush()
        await self._set_primary_projection(ticket, target, actor.user_id)

        user = await self.user_repository.get_by_id(target.user_id)
        await self._audit(
            ticket_id,
            AuditEventType.PRIMARY_CHANGED,
            actor,
            old_values={"agent_id": old_agent_id},
            new_values={"agent_id": target.user_id, "agent_name": user.name if user else None},
        )
        if self.escalation_service is not None:
            await self.escalation_service.acknowledge_via_assignment(ticket_id, actor)
        await self._notify({target.user_id} - {actor.user_id}, "You are now the primary assignee on a ticket", ticket)
        return target

    async def remove_assignment(
        self,
        ticket_id: UUID,
        assignment_id: UUID,
        actor: User,
        *,
        new_primary_assignment_id: UUID | None = None,
    ) -> None:
        """
        Unassign one user (soft delete — history and SLA runs kept; the
        live run completes with reason UNASSIGNED). Removing the
        primary while others remain requires naming the new primary
        explicitly — never an automatic, silent accountability change.
        Removing the only assignee returns the ticket to the pool.
        """

        ticket = await self._lock_ticket(ticket_id)
        await self._ensure_can_manage(ticket, actor)
        ensure_can_reassign_ticket(actor)
        target = await self.get_assignment_on_ticket(ticket_id, assignment_id)
        active = await self.repository.list_active(ticket_id)
        others = [a for a in active if a.assignment_id != target.assignment_id]

        new_primary: TicketAssignment | None = None
        if target.is_primary and others:
            if new_primary_assignment_id is None:
                raise _bad_request("Choose a new primary user before removing the current primary.")
            new_primary = next(
                (a for a in others if a.assignment_id == new_primary_assignment_id), None
            )
            if new_primary is None:
                raise _bad_request("The new primary must be another user already assigned to this ticket.")

        was_primary = target.is_primary
        user = await self.user_repository.get_by_id(target.user_id)
        await self._soft_remove(target, actor.user_id)
        await self._audit(
            ticket_id,
            AuditEventType.USER_UNASSIGNED,
            actor,
            old_values=snapshot(target).as_audit() | {"is_primary": was_primary},
            new_values={"user_name": user.name if user else None},
        )

        if was_primary:
            if new_primary is not None:
                new_primary.is_primary = True
                await self.repository.flush()
            await self._set_primary_projection(ticket, new_primary, actor.user_id)
            new_user = (
                await self.user_repository.get_by_id(new_primary.user_id) if new_primary else None
            )
            await self._audit(
                ticket_id,
                AuditEventType.PRIMARY_CHANGED,
                actor,
                old_values={"agent_id": target.user_id},
                new_values={
                    "agent_id": new_primary.user_id if new_primary else None,
                    "agent_name": new_user.name if new_user else None,
                },
            )
            if new_primary is not None:
                await self._notify(
                    {new_primary.user_id} - {actor.user_id},
                    "You are now the primary assignee on a ticket",
                    ticket,
                )

    # ---------------------------------------------------------
    # Categories
    # ---------------------------------------------------------

    async def sync_primary_category(
        self, ticket: Ticket, category_name: str | None, *, actor_id: UUID | None
    ) -> None:
        """
        Projection keeper for every existing single-category writer
        (create, transfer_agent's cross-category move, PATCH
        ticket_type): the named category becomes the PRIMARY ticket
        category — a move, so the previous primary row is replaced.
        Secondary categories are untouched. Unknown names are skipped
        (ticket_type itself is never rejected here — that stays the
        caller's existing validation, unchanged).
        """

        if not category_name:
            return
        category = await self.repository.get_category_by_name(category_name)
        if category is None:
            return

        rows = await self.repository.list_categories(ticket.ticket_id)
        current_primary = next((tc for tc, _ in rows if tc.is_primary), None)
        if current_primary is not None and current_primary.category_id == category.category_id:
            return

        if current_primary is not None:
            await self.repository.delete_category(current_primary)

        existing = next((tc for tc, _ in rows if tc.category_id == category.category_id), None)
        if existing is not None:
            existing.is_primary = True
            await self.repository.flush()
        else:
            await self.repository.add_category(
                TicketCategory(
                    ticket_id=ticket.ticket_id,
                    category_id=category.category_id,
                    is_primary=True,
                    assigned_by=actor_id,
                )
            )
        ticket.category_names = None

    async def attach_categories_on_create(
        self, ticket: Ticket, category_names: list[str], actor: User
    ) -> None:
        """
        Secondary categories picked while CREATING a ticket. Choosing a
        new ticket's categories is part of creating it (ticket:create,
        already enforced by the caller, which also validated every name
        exists) — the same reason the primary category needs no
        ticket:change_category at creation. Audited like add_category.
        """

        existing = {name for _, name in await self.repository.list_categories(ticket.ticket_id)}
        for name in category_names:
            if name in existing:
                continue
            category = await self.repository.get_category_by_name(name)
            if category is None:
                raise _bad_request(f"Category {name!r} does not exist.")
            await self.repository.add_category(
                TicketCategory(
                    ticket_id=ticket.ticket_id,
                    category_id=category.category_id,
                    is_primary=False,
                    assigned_by=actor.user_id,
                )
            )
            existing.add(name)
            await self._audit(
                ticket.ticket_id,
                AuditEventType.CATEGORY_ADDED,
                actor,
                new_values={
                    "category_id": category.category_id,
                    "category_name": name,
                    "is_primary": False,
                },
            )
        ticket.category_names = None

    async def add_category(self, ticket_id: UUID, category_id: UUID, actor: User) -> TicketCategory:
        ticket = await self._lock_ticket(ticket_id)
        await self._ensure_can_manage(ticket, actor)
        ensure_has_permission(actor, "ticket:change_category")

        category = await self.repository.get_category_by_id(category_id)
        if category is None:
            raise _bad_request("Category does not exist.")
        if await self.repository.get_ticket_category(ticket_id, category_id) is not None:
            raise _conflict("This category is already on the ticket.")

        rows = await self.repository.list_categories(ticket_id)
        ticket_category = await self.repository.add_category(
            TicketCategory(
                ticket_id=ticket_id,
                category_id=category_id,
                is_primary=not rows,
                assigned_by=actor.user_id,
            )
        )
        if not rows:
            ticket.ticket_type = category.category_name
            await self.repository.flush()
        await self._audit(
            ticket_id,
            AuditEventType.CATEGORY_ADDED,
            actor,
            new_values={
                "category_id": category_id,
                "category_name": category.category_name,
                "is_primary": ticket_category.is_primary,
            },
        )
        return ticket_category

    async def remove_category(self, ticket_id: UUID, category_id: UUID, actor: User) -> None:
        """
        Never leaves a ticket category-less, and never strands an
        assignee: if removing this category would make any active
        Team Lead/Staff assignee lose RBAC visibility, the request is
        rejected (409) rather than silently hiding the ticket from
        someone assigned to it. Removing the primary promotes the
        oldest remaining category and moves ticket_type with it.
        """

        ticket = await self._lock_ticket(ticket_id)
        await self._ensure_can_manage(ticket, actor)
        ensure_has_permission(actor, "ticket:change_category")

        rows = await self.repository.list_categories(ticket_id)
        target = next(((tc, name) for tc, name in rows if tc.category_id == category_id), None)
        if target is None:
            raise _not_found("Category not found on this ticket.")
        remaining = [(tc, name) for tc, name in rows if tc.category_id != category_id]
        if not remaining:
            raise _bad_request("A ticket must keep at least one category.")

        remaining_names = {name for _, name in remaining}
        stranded = []
        for assignment in await self.repository.list_active(ticket_id):
            user = await self.user_repository.get_by_id(assignment.user_id)
            if user is None or user.role is None or user.role.name not in CATEGORY_SCOPED_ROLE_NAMES:
                continue
            if not {c.category_name for c in (user.categories or [])} & remaining_names:
                stranded.append(user.name)
        if stranded:
            raise _conflict(
                "Removing this category would leave these assigned users unable to see the ticket: "
                + ", ".join(stranded)
            )

        ticket_category, name = target
        was_primary = ticket_category.is_primary
        await self.repository.delete_category(ticket_category)
        new_primary_name = None
        if was_primary:
            new_primary_tc, new_primary_name = remaining[0]
            new_primary_tc.is_primary = True
            ticket.ticket_type = new_primary_name
            await self.repository.flush()
        await self._audit(
            ticket_id,
            AuditEventType.CATEGORY_REMOVED,
            actor,
            old_values={"category_id": category_id, "category_name": name, "is_primary": was_primary},
            new_values={"primary_category_name": new_primary_name} if was_primary else None,
        )


async def sweep_assignment_sla_breaches(
    db: AsyncSession,
    *,
    now: datetime,
    notification_service: NotificationService | None = None,
) -> int:
    """
    SLA-sweep step for per-assignee Resolution runs. Stamps breached_at
    exactly once per run (the stamp is the idempotency guard — a run
    already stamped is never selected again), and notifies the assignee
    of a NON-primary run. The primary's breach is already covered by
    the unchanged ticket-level Resolution ladder + auto-escalation, so
    it is stamped (for reporting) but not double-notified. Never
    escalates — escalation stays ticket-level / primary-owned.
    """

    repository = TicketAssignmentRepository(db)
    runs = await repository.list_running_overdue_unbreached(now)
    for run in runs:
        run.breached_at = run.due_at
    await repository.flush()

    if notification_service is not None:
        for run in runs:
            assignment = await repository.get(run.assignment_id)
            if assignment is None or assignment.is_primary or assignment.removed_at is not None:
                continue
            await notification_service.notify(
                assignment.user_id,
                NotificationType.SLA_BREACHED,
                title="Your resolution SLA on a ticket was breached",
                message="Your assignment on this ticket is past its resolution target.",
                link=f"/tickets/{run.ticket_id}",
                related_entity_type="ticket",
                related_entity_id=run.ticket_id,
            )
    return len(runs)


def build_ticket_assignment_service(
    db: AsyncSession,
    *,
    notification_service: NotificationService | None = None,
    escalation_service=None,
) -> TicketAssignmentService:
    return TicketAssignmentService(
        db,
        notification_service=notification_service,
        escalation_service=escalation_service,
    )

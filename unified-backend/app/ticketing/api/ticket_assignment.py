"""
Multi-user / multi-category assignment endpoints — same /tickets prefix
and conventions as api/ticket.py. All business rules live in
TicketAssignmentService; individual status changes are routed through
InteractionService.change_status so the primary's status keeps driving
the ticket-level status/SLA exactly as the existing status endpoint does.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent, get_current_user
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.rbac.api.v1.permission_requests import get_permission_request_service
from app.ticketing.enums import SLAClockStatus, TicketStatus
from app.ticketing.models.ticket_assignment_sla import TicketAssignmentSLA
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_escalation_repository import (
    TicketEscalationRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.ticket_action import StatusChangeRequest
from app.ticketing.schemas.ticket_assignment import (
    AddTicketCategoryRequest,
    AssignmentSLARunState,
    AssignUsersRequest,
    TicketAssignmentItem,
    TicketAssignmentsResponse,
    TicketCategoryItem,
    UpdateAssignmentRequest,
)
from app.ticketing.services.access_control import (
    ensure_agent_can_view_ticket_including_escalated,
)
from app.ticketing.services.escalation_service import build_escalation_service
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.sla_service import build_sla_service
from app.ticketing.services.ticket_assignment_service import (
    build_ticket_assignment_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tickets",
    tags=["Ticket Assignments"],
)


def _run_state(run: TicketAssignmentSLA, now: datetime) -> AssignmentSLARunState:
    live = run.status != SLAClockStatus.COMPLETED
    reference = run.paused_at if run.status == SLAClockStatus.PAUSED and run.paused_at else now
    remaining = int((run.due_at - reference).total_seconds()) if live else None
    target_seconds = run.active_target_minutes * 60
    elapsed_fraction = (
        round(1 - remaining / target_seconds, 4)
        if live and target_seconds > 0 and remaining is not None
        else None
    )
    breached = run.breached_at is not None or (
        run.status == SLAClockStatus.RUNNING and run.due_at < now
    )
    return AssignmentSLARunState(
        assignment_sla_id=run.assignment_sla_id,
        run_number=run.run_number,
        priority=run.priority,
        status=run.status,
        started_at=run.started_at,
        due_at=run.due_at,
        active_target_minutes=run.active_target_minutes,
        paused_at=run.paused_at,
        total_paused_seconds=run.total_paused_seconds,
        completed_at=run.completed_at,
        completion_reason=run.completion_reason,
        breached=breached,
        breached_at=run.breached_at,
        remaining_seconds=remaining,
        elapsed_fraction=elapsed_fraction,
    )


async def _resync_reviewers(db: AsyncSession, ticket_id: UUID, owner_id: UUID | None) -> None:
    """Same best-effort reviewer resync claim/transfer already do."""

    if owner_id is None:
        return
    try:
        await get_permission_request_service(db).resync_ticket_scoped_reviewers(ticket_id, owner_id)
    except Exception:
        logger.warning("PERMISSION_REQUEST_REVIEWER_RESYNC_FAILED", exc_info=True)


def _notification_service(db: AsyncSession) -> NotificationService:
    return NotificationService(NotificationRepository(db))


def _assignment_service(db: AsyncSession):
    notification_service = _notification_service(db)
    return build_ticket_assignment_service(
        db,
        notification_service=notification_service,
        escalation_service=build_escalation_service(db, notification_service=notification_service),
    )


async def _build_response(db: AsyncSession, ticket_id: UUID) -> TicketAssignmentsResponse:
    ticket_repository = TicketRepository(db)
    ticket = await ticket_repository.get_by_id(ticket_id)
    service = build_ticket_assignment_service(db)
    repository = service.repository
    assignments = await repository.list_active(ticket_id)
    categories = await repository.list_categories(ticket_id)
    runs = await repository.list_runs_for_ticket(ticket_id)

    user_ids = {a.user_id for a in assignments} | {a.assigned_by for a in assignments if a.assigned_by}
    names = await UserRepository(db).get_names_by_ids(list(user_ids)) if user_ids else {}

    now = datetime.now(timezone.utc)
    runs_by_assignment: dict[UUID, list[TicketAssignmentSLA]] = {}
    for run in runs:
        runs_by_assignment.setdefault(run.assignment_id, []).append(run)

    items = []
    for assignment in assignments:
        history = [_run_state(r, now) for r in runs_by_assignment.get(assignment.assignment_id, [])]
        current = next((h for h in reversed(history) if h.status != SLAClockStatus.COMPLETED), None)
        if current is None and history:
            current = history[-1]
        items.append(
            TicketAssignmentItem(
                assignment_id=assignment.assignment_id,
                user_id=assignment.user_id,
                user_name=names.get(assignment.user_id),
                is_primary=assignment.is_primary,
                status=assignment.status,
                assigned_by=assignment.assigned_by,
                assigned_by_name=names.get(assignment.assigned_by) if assignment.assigned_by else None,
                assigned_at=assignment.assigned_at,
                status_changed_at=assignment.status_changed_at,
                closed_at=assignment.closed_at,
                resolution_sla=current,
                sla_history=history,
            )
        )

    return TicketAssignmentsResponse(
        ticket_id=ticket_id,
        ticket_status=ticket.current_status,
        is_closed=ticket.current_status == TicketStatus.CLOSED,
        closed_at=ticket.closed_at if ticket.current_status == TicketStatus.CLOSED else None,
        closed_by=ticket.closed_by,
        assignments=items,
        categories=[
            TicketCategoryItem(
                category_id=tc.category_id,
                category_name=name,
                is_primary=tc.is_primary,
                assigned_at=tc.assigned_at,
            )
            for tc, name in categories
        ],
    )


@router.get(
    "/{ticket_id}/assignments",
    response_model=TicketAssignmentsResponse,
)
async def get_ticket_assignments(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every active assignee (with individual status + SLA) and every category."""

    ticket = await TicketRepository(db).get_by_id(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found.")
    await ensure_agent_can_view_ticket_including_escalated(
        ticket, current_user, ClientRepository(db), TicketEscalationRepository(db)
    )
    return await _build_response(db, ticket_id)


@router.post(
    "/{ticket_id}/assignments",
    response_model=TicketAssignmentsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_users(
    ticket_id: UUID,
    request: AssignUsersRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Assign one or many users (all-or-nothing)."""

    service = _assignment_service(db)
    before = await service.get_primary(ticket_id)
    await service.add_users(
        ticket_id,
        request.user_ids,
        current_user,
        primary_user_id=request.primary_user_id,
    )
    after = await service.get_primary(ticket_id)
    if after is not None and (before is None or before.user_id != after.user_id):
        await _resync_reviewers(db, ticket_id, after.user_id)
    return await _build_response(db, ticket_id)


@router.patch(
    "/{ticket_id}/assignments/{assignment_id}",
    response_model=TicketAssignmentsResponse,
)
async def update_assignment(
    ticket_id: UUID,
    assignment_id: UUID,
    request: UpdateAssignmentRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Change one assignee's individual status and/or promote them to primary."""

    service = _assignment_service(db)
    await service.get_assignment_on_ticket(ticket_id, assignment_id)

    if request.is_primary:
        promoted = await service.change_primary(ticket_id, assignment_id, current_user)
        await _resync_reviewers(db, ticket_id, promoted.user_id)

    if request.status is not None:
        notification_service = _notification_service(db)
        interaction_service = InteractionService(
            interaction_repository=InteractionRepository(db),
            ticket_repository=TicketRepository(db),
            user_repository=UserRepository(db),
            client_repository=ClientRepository(db),
            sla_service=build_sla_service(db),
            escalation_service=build_escalation_service(db),
            notification_service=notification_service,
        )
        await interaction_service.change_status(
            ticket_id=ticket_id,
            request=StatusChangeRequest(new_status=request.status, assignment_id=assignment_id),
            current_user=current_user,
        )

    return await _build_response(db, ticket_id)


@router.delete(
    "/{ticket_id}/assignments/{assignment_id}",
    response_model=TicketAssignmentsResponse,
)
async def remove_assignment(
    ticket_id: UUID,
    assignment_id: UUID,
    new_primary_assignment_id: UUID | None = Query(default=None),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Unassign one user. Removing the primary requires new_primary_assignment_id when others remain."""

    service = _assignment_service(db)
    before = await service.get_primary(ticket_id)
    await service.remove_assignment(
        ticket_id,
        assignment_id,
        current_user,
        new_primary_assignment_id=new_primary_assignment_id,
    )
    after = await service.get_primary(ticket_id)
    if after is not None and (before is None or before.user_id != after.user_id):
        await _resync_reviewers(db, ticket_id, after.user_id)
    return await _build_response(db, ticket_id)


@router.post(
    "/{ticket_id}/categories",
    response_model=TicketAssignmentsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_ticket_category(
    ticket_id: UUID,
    request: AddTicketCategoryRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    await _assignment_service(db).add_category(ticket_id, request.category_id, current_user)
    return await _build_response(db, ticket_id)


@router.delete(
    "/{ticket_id}/categories/{category_id}",
    response_model=TicketAssignmentsResponse,
)
async def remove_ticket_category(
    ticket_id: UUID,
    category_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    await _assignment_service(db).remove_category(ticket_id, category_id, current_user)
    return await _build_response(db, ticket_id)

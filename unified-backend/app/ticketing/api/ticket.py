from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.ticketing.enums import (
    AuditEntityType,
    AuditEventType,
    InteractionDirection,
    InteractionStatus,
    TicketPriority,
    TicketStatus,
)

from app.database.session import get_db
from app.dependencies.auth import get_current_agent, get_current_user
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService

from app.ticketing.repositories.attachment_repository import (
    AttachmentRepository,
)
from app.ticketing.repositories.audit_log_repository import (
    AuditLogRepository,
)
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import (
    InteractionRepository,
)
from app.ticketing.repositories.ticket_edit_access_repository import (
    TicketEditAccessRequestRepository,
)
from app.ticketing.repositories.ticket_relation_repository import TicketRelationRepository
from app.ticketing.repositories.ticket_repository import (
    TicketRepository,
)
from app.ticketing.repositories.user_repository import UserRepository

from app.ticketing.schemas.attach_interaction import (
    AttachInteractionRequest,
    AttachInteractionResponse,
)
from app.ticketing.schemas.attachment import (
    AttachmentUploadResponse,
)
from app.ticketing.schemas.audit_log import AuditLogResponse, TicketAuditLogResponse
from app.ticketing.schemas.edit_access import (
    EditAccessApproveRequest,
    EditAccessRejectRequest,
    EditAccessRequestCreate,
    EditAccessRequestResponse,
)
from app.ticketing.schemas.interaction import (
    HideInteractionRequest,
    HideInteractionResponse,
    InteractionResponse,
    TicketInteractionResponse,
)
from app.ticketing.schemas.note import (
    InternalNoteCreate,
    InternalNoteResponse,
)
from app.ticketing.schemas.ticket import (
    DashboardStatsResponse,
    RelateTicketRequest,
    RelateTicketResponse,
    SLAOverviewCountsResponse,
    TicketListItemResponse,
    TicketResponse,
    TicketUpdate,
    UnrelateTicketResponse,
)
from app.ticketing.schemas.ticket_action import (
    PriorityChangeRequest,
    ReplyCreate,
    StatusChangeRequest,
    TicketActionResponse,
    TransferAgentRequest,
)
from app.ticketing.schemas.ticket_from_interaction import (
    TicketFromInteractionCreate,
    TicketFromInteractionResponse,
)

from app.ticketing.services.assignment_service import AssignmentService
from app.ticketing.services.attachment_service import AttachmentService
from app.ticketing.services.edit_access_service import EditAccessService
from app.ticketing.services.escalation_service import build_escalation_service
from app.ticketing.services.inbox_ticket_service import InboxTicketService
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.sla_service import build_sla_service
from app.ticketing.services.ticket_service import TicketService
from app.ticketing.storage import get_storage_service

router = APIRouter(
    prefix="/tickets",
    tags=["Tickets"],
)


# =========================================================
# Workflow 1
# Create Ticket From Inbox Interaction
# =========================================================

@router.post(
    "/from-interaction",
    response_model=TicketFromInteractionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ticket_from_interaction(
    request: TicketFromInteractionCreate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new ticket from a pending inbox interaction. The whole
    thread already exchanged under that interaction (if any) moves
    onto the new ticket's timeline too.
    """

    ticket_repository = TicketRepository(db)
    interaction_repository = InteractionRepository(db)
    assignment_service = AssignmentService(UserRepository(db))

    service = InboxTicketService(
        ticket_repository=ticket_repository,
        interaction_repository=interaction_repository,
        assignment_service=assignment_service,
        sla_service=build_sla_service(
            db, notification_service=NotificationService(NotificationRepository(db))
        ),
    )

    return await service.create_ticket_from_interaction(request, current_user=current_user)


# =========================================================
# Workflow 2
# Attach Interaction To Existing Ticket
# =========================================================

@router.post(
    "/{ticket_id}/attach-interaction",
    response_model=AttachInteractionResponse,
    status_code=status.HTTP_200_OK,
)
async def attach_interaction_to_ticket(
    ticket_id: UUID,
    request: AttachInteractionRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):

    ticket_repository = TicketRepository(db)
    interaction_repository = InteractionRepository(db)

    service = InboxTicketService(
        ticket_repository=ticket_repository,
        interaction_repository=interaction_repository,
        sla_service=build_sla_service(
            db, notification_service=NotificationService(NotificationRepository(db))
        ),
    )

    return await service.attach_to_existing_ticket(
        ticket_id=ticket_id,
        request=request,
        current_user=current_user,
    )


# =========================================================
# Ticket Timeline
# =========================================================

@router.get(
    "/{ticket_id}/interactions",
    response_model=list[InteractionResponse],
    status_code=status.HTTP_200_OK,
)
async def get_ticket_interactions(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    attachment_repository = AttachmentRepository(db)
    audit_log_repository = AuditLogRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        attachment_repository=attachment_repository,
        storage_service=get_storage_service(),
        audit_log_repository=audit_log_repository,
    )

    return await service.get_ticket_interactions(ticket_id, current_user=current_user)


# =========================================================
# Ticket Audit Trail
# =========================================================

@router.get(
    "/{ticket_id}/audit-logs",
    response_model=list[AuditLogResponse],
    status_code=status.HTTP_200_OK,
)
async def get_ticket_audit_logs(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the complete, immutable audit trail for a ticket, newest
    first.

    Includes both the direct ticket-level events (create, update,
    status/priority change, transfer) and the events logged against
    the ticket's interactions and attachments (notes, replies, hides,
    uploads).
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    audit_log_repository = AuditLogRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        audit_log_repository=audit_log_repository,
    )

    return await service.get_ticket_audit_logs(ticket_id, current_user=current_user)


# =========================================================
# Internal Note
# =========================================================

@router.post(
    "/{ticket_id}/notes",
    response_model=InternalNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_internal_note(
    ticket_id: UUID,
    request: InternalNoteCreate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    edit_access_repository = TicketEditAccessRequestRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        edit_access_repository=edit_access_repository,
    )

    return await service.add_internal_note(
        ticket_id=ticket_id,
        request=request,
        current_user=current_user,
    )


# =========================================================
# Reply To Client
# =========================================================

@router.post(
    "/{ticket_id}/reply",
    response_model=TicketActionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reply_to_client(
    ticket_id: UUID,
    request: ReplyCreate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Sends a reply to the client on this ticket.

    Stored as an OUTBOUND interaction on the ticket timeline, with a
    full outbound envelope built when the ticket's client and prior
    inbound email can be resolved.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    edit_access_repository = TicketEditAccessRequestRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
        edit_access_repository=edit_access_repository,
    )

    return await service.add_reply(
        ticket_id=ticket_id,
        request=request,
        current_user=current_user,
    )


# =========================================================
# Claim Ticket
# =========================================================

@router.post(
    "/{ticket_id}/claim",
    response_model=TicketActionResponse,
    status_code=status.HTTP_200_OK,
)
async def claim_ticket(
    ticket_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Claims an unassigned open ticket from the shared pool for the
    calling agent. 409 if it's already been claimed (by anyone,
    including a race with another agent claiming at the same time).
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
    )

    return await service.claim_ticket(
        ticket_id=ticket_id,
        current_user=current_user,
    )


# =========================================================
# Status Change
# =========================================================

@router.post(
    "/{ticket_id}/status",
    response_model=TicketActionResponse,
    status_code=status.HTTP_200_OK,
)
async def change_ticket_status(
    ticket_id: UUID,
    request: StatusChangeRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Changes the ticket's status and records the
    change as an interaction on the timeline.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    edit_access_repository = TicketEditAccessRequestRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        edit_access_repository=edit_access_repository,
        sla_service=build_sla_service(db),
    )

    return await service.change_status(
        ticket_id=ticket_id,
        request=request,
        current_user=current_user,
    )


# =========================================================
# Priority Change
# =========================================================

@router.post(
    "/{ticket_id}/priority",
    response_model=TicketActionResponse,
    status_code=status.HTTP_200_OK,
)
async def change_ticket_priority(
    ticket_id: UUID,
    request: PriorityChangeRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Changes the ticket's priority and records the
    change as an interaction on the timeline.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        sla_service=build_sla_service(db),
    )

    return await service.change_priority(
        ticket_id=ticket_id,
        request=request,
        current_user=current_user,
    )


# =========================================================
# Attachment Upload
# =========================================================

@router.post(
    "/{ticket_id}/attachments",
    response_model=AttachmentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_ticket_attachment(
    ticket_id: UUID,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Uploads one or more files to this ticket.

    Recorded as a single interaction on the timeline,
    with each file's metadata stored as its own Attachment row.
    """

    attachment_repository = AttachmentRepository(db)
    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)

    service = AttachmentService(
        attachment_repository=attachment_repository,
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        storage_service=get_storage_service(),
    )

    return await service.upload_attachment(
        ticket_id=ticket_id,
        files=files,
        current_user=current_user,
    )


# =========================================================
# Hide / Soft-Delete Interaction
# =========================================================

@router.post(
    "/{ticket_id}/interactions/{interaction_id}/hide",
    response_model=HideInteractionResponse,
    status_code=status.HTTP_200_OK,
)
async def hide_ticket_interaction(
    ticket_id: UUID,
    interaction_id: UUID,
    request: HideInteractionRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Hides (soft-deletes) an interaction on this ticket.

    The interaction row is never physically deleted;
    it is marked not visible so the timeline and audit
    trail remain intact.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
    )

    return await service.hide_interaction(
        ticket_id=ticket_id,
        interaction_id=interaction_id,
        request=request,
        current_user=current_user,
    )


# =========================================================
# Transfer Agent
# =========================================================

@router.post(
    "/{ticket_id}/transfer",
    response_model=TicketActionResponse,
    status_code=status.HTTP_200_OK,
)
async def transfer_ticket_agent(
    ticket_id: UUID,
    request: TransferAgentRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Transfers full ownership of a ticket to a different
    active Staff member. The previous agent has no further
    rights on the ticket once this completes, and the change
    is recorded as an interaction on the timeline.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        notification_service=NotificationService(NotificationRepository(db)),
        escalation_service=build_escalation_service(
            db, notification_service=NotificationService(NotificationRepository(db))
        ),
    )

    return await service.transfer_agent(
        ticket_id=ticket_id,
        request=request,
        current_user=current_user,
    )


# =========================================================
# Close Ticket
# =========================================================

@router.post(
    "/{ticket_id}/close",
    response_model=TicketActionResponse,
    status_code=status.HTTP_200_OK,
)
async def close_ticket(
    ticket_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Closes a ticket — the only transition that completes the
    Resolution SLA clock. A closed ticket becomes read-only until
    reopened (see POST /tickets/{ticket_id}/reopen).
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    edit_access_repository = TicketEditAccessRequestRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        edit_access_repository=edit_access_repository,
        sla_service=build_sla_service(db),
    )

    return await service.close_ticket(
        ticket_id=ticket_id,
        current_user=current_user,
    )


# =========================================================
# Reopen Ticket
# =========================================================

@router.post(
    "/{ticket_id}/reopen",
    response_model=TicketActionResponse,
    status_code=status.HTTP_200_OK,
)
async def reopen_ticket(
    ticket_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Reopens a closed ticket, restoring every action a closed ticket
    otherwise blocks (reply, notes, attachments, status/priority
    changes, transfer).
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    edit_access_repository = TicketEditAccessRequestRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        edit_access_repository=edit_access_repository,
        sla_service=build_sla_service(db),
    )

    return await service.reopen_ticket(
        ticket_id=ticket_id,
        current_user=current_user,
    )


# =========================================================
# Related Tickets
# =========================================================

@router.post(
    "/{ticket_id}/related",
    response_model=RelateTicketResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_related_ticket(
    ticket_id: UUID,
    request: RelateTicketRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Links this ticket to another one — symmetric, both tickets show
    each other under "Related Tickets" afterward.
    """

    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    ticket_relation_repository = TicketRelationRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
        ticket_relation_repository=ticket_relation_repository,
    )

    return await service.add_related_ticket(
        ticket_id=ticket_id,
        request=request,
        current_user=current_user,
    )


@router.delete(
    "/{ticket_id}/related/{related_ticket_id}",
    response_model=UnrelateTicketResponse,
    status_code=status.HTTP_200_OK,
)
async def remove_related_ticket(
    ticket_id: UUID,
    related_ticket_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Unlinks two related tickets — symmetric, removes both directions."""

    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    ticket_relation_repository = TicketRelationRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
        ticket_relation_repository=ticket_relation_repository,
    )

    return await service.remove_related_ticket(
        ticket_id=ticket_id,
        related_ticket_id=related_ticket_id,
        current_user=current_user,
    )


# =========================================================
# Update Ticket
# =========================================================

@router.patch(
    "/{ticket_id}",
    response_model=TicketResponse,
    status_code=status.HTTP_200_OK,
)
async def update_ticket(
    ticket_id: UUID,
    request: TicketUpdate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Updates ticket fields directly (title, ticket_type,
    custom_fields, closed_at).

    For status, priority, and agent, prefer the dedicated
    /status, /priority, and /transfer endpoints so the
    change is also recorded on the ticket timeline.
    """

    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.update(
        ticket_id=ticket_id,
        request=request,
        current_user=current_user,
    )


# =========================================================
# List Tickets
# =========================================================

@router.get(
    "",
    response_model=list[TicketListItemResponse],
    status_code=status.HTTP_200_OK,
)
async def list_tickets(
    response: Response,
    limit: int | None = Query(None, ge=1, le=200),
    offset: int = Query(0, ge=0),
    ticket_status: TicketStatus | None = Query(None, alias="status"),
    priority: TicketPriority | None = Query(None),
    ticket_type: str | None = Query(None),
    view: str | None = Query(None, pattern="^(pool|mine|all|escalated)$"),
    search: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    sort_by: str = Query("created_at", pattern="^(created_at|updated_at|title)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns tickets, most recently created first. Account Manager is
    scoped to their own clients' tickets; Team Lead/Staff are scoped
    to their own work-specialization category's shared pool; Site
    Lead/Super Admin see every ticket. See TicketService.list_all.

    Returns `TicketListItemResponse` (not the full `TicketResponse` —
    see that schema's own docstring), dropping `custom_fields`/
    `related_tickets`, neither of which any list view reads.
    GET /tickets/{id} (detail) is unaffected and still returns the
    full shape.

    `limit`/`offset` (plus the filter params) are all optional and
    additive: omitting `limit` returns the exact same unbounded
    response this endpoint always returned. Passing `limit` bounds the
    query and reports the matching total via `X-Total-Count`. `view`
    is the ticket-list page's own Open Pool/My Tickets/All tab filter
    (`"mine"` resolves against the caller's own id, never a caller-
    supplied one) — orthogonal to the status/priority/category
    filters, all of which can be combined with any tab.
    """

    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    items, total = await service.list_all(
        current_user=current_user,
        limit=limit,
        offset=offset,
        status_filter=ticket_status,
        priority_filter=priority,
        ticket_type_filter=ticket_type,
        view=view,
        search=search,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )

    if limit is not None:
        response.headers["X-Total-Count"] = str(total)

    return items


@router.get(
    "/view-counts",
    status_code=status.HTTP_200_OK,
)
async def get_ticket_view_counts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    The ticket-list page's three tab badges (Open Pool / My Tickets /
    All) — one grouped query under the same visibility scoping as
    GET /tickets itself, so the page never needs to fetch all three
    tabs' full row sets just to show a count on each. See
    TicketService.count_by_view.
    """

    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.count_by_view(current_user=current_user)


@router.get(
    "/dashboard-stats",
    response_model=DashboardStatsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_ticket_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Every stat card and small ticket list the ticket-workspace
    Dashboard needs, computed server-side under the same visibility
    scoping as GET /tickets — replaces the Dashboard's old
    `listTickets()` call, which fetched every visible ticket unbounded
    just to derive these numbers client-side. See
    TicketService.get_dashboard_stats.
    """

    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.get_dashboard_stats(current_user=current_user)


@router.get(
    "/sla-overview-counts",
    response_model=SLAOverviewCountsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_ticket_sla_overview_counts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    The Dashboard's "SLA Overview" tile row (Running/Paused/At Risk/
    Breached/Escalated/Completed), computed server-side in one grouped
    query — replaces the frontend's old N+1 pattern (an unbounded
    GET /tickets fetch, then one GET /tickets/{id}/sla call per visible
    ticket) that used to back this same tile. See
    TicketService.get_sla_overview_counts.
    """

    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
    )

    return await service.get_sla_overview_counts(current_user=current_user)


# =========================================================
# List Audit Logs Across Every Visible Ticket
# =========================================================

# NOTE: this static route must stay registered before the bare
# GET "/{ticket_id}" below — {ticket_id} is an untyped path segment,
# so a request to /tickets/audit-logs registered after it would match
# {ticket_id}="audit-logs" first and 422 on UUID coercion instead of
# ever reaching this route.
@router.get(
    "/audit-logs",
    response_model=list[TicketAuditLogResponse],
    status_code=status.HTTP_200_OK,
)
async def list_all_ticket_audit_logs(
    response: Response,
    limit: int | None = Query(None, ge=1, le=200),
    offset: int = Query(0, ge=0),
    entity_type: AuditEntityType | None = Query(None),
    event_type: AuditEventType | None = Query(None),
    actor_name: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    search: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns every audit-log row for every ticket the caller can see,
    in one query — the same visibility scoping as GET /tickets. Used
    by the Audit Log page instead of fetching the ticket list and then
    each ticket's own audit trail one request at a time.

    `limit`/`offset` (plus the filter params) are all optional and
    additive — omitting `limit` returns the exact same unbounded
    response this endpoint always returned. Passing `limit` bounds the
    query and reports the matching total via `X-Total-Count` — this
    matters more here than almost anywhere else in the app, since the
    Audit Log page polls this endpoint every 15 seconds.
    """

    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    audit_log_repository = AuditLogRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
        audit_log_repository=audit_log_repository,
    )

    items, total = await service.list_all_audit_logs(
        current_user=current_user,
        limit=limit,
        offset=offset,
        entity_type=entity_type,
        event_type=event_type,
        actor_name=actor_name,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )

    if limit is not None:
        response.headers["X-Total-Count"] = str(total)

    return items


# =========================================================
# List Interactions Across Every Visible Ticket
# =========================================================

# Same static-route-before-{ticket_id} ordering requirement as
# /audit-logs above.
@router.get(
    "/interactions",
    response_model=list[TicketInteractionResponse],
    status_code=status.HTTP_200_OK,
)
async def list_all_ticket_interactions(
    response: Response,
    limit: int | None = Query(None, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(None),
    interaction_type: str | None = Query(None),
    direction: InteractionDirection | None = Query(None),
    interaction_status: InteractionStatus | None = Query(None, alias="status"),
    agent_id: UUID | None = Query(None),
    ticket_id: UUID | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    search: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns every interaction across every ticket the caller can see,
    in one query — the same visibility scoping as GET /tickets. Used
    by the Interactions page instead of fetching the ticket list and
    then each ticket's own timeline one request at a time.

    `limit`/`offset` (plus the filter params) are all optional and
    additive: a caller that omits `limit` gets the exact same
    unbounded, unfiltered response this endpoint always returned (the
    standalone `ticketing-service/frontend` still calls it this way).
    Passing `limit` switches the query itself to a bounded, filtered
    one and reports the matching total via `X-Total-Count` so a
    paginated caller (the embedded Interactions page) can show
    "Showing X-Y of Z" without a second round trip. `cursor` (from a
    previous response's `X-Next-Cursor` header) is an additive keyset-
    paging alternative to `offset` for deep paging at scale — pass
    either, not both.
    """

    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    interaction_repository = InteractionRepository(db)
    attachment_repository = AttachmentRepository(db)
    audit_log_repository = AuditLogRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        client_repository=client_repository,
        interaction_repository=interaction_repository,
        attachment_repository=attachment_repository,
        storage_service=get_storage_service(),
        audit_log_repository=audit_log_repository,
    )

    items, total, next_cursor = await service.list_all_interactions(
        current_user=current_user,
        limit=limit,
        offset=offset,
        cursor=cursor,
        interaction_type=interaction_type,
        direction=direction,
        interaction_status=interaction_status,
        agent_id=agent_id,
        ticket_id=ticket_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )

    if limit is not None:
        response.headers["X-Total-Count"] = str(total)
        if next_cursor is not None:
            response.headers["X-Next-Cursor"] = next_cursor

    return items


# =========================================================
# Get Ticket Details
# =========================================================

@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    status_code=status.HTTP_200_OK,
)
async def get_ticket(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns ticket details.

    This endpoint returns only the ticket metadata.
    Ticket interactions (timeline) are retrieved
    using a separate endpoint.
    """

    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    ticket_relation_repository = TicketRelationRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        ticket_relation_repository=ticket_relation_repository,
        client_repository=client_repository,
    )

    return await service.get_by_id(ticket_id, current_user=current_user)


# =========================================================
# Edit Access — Request / Approve / Reject
# =========================================================


def _get_edit_access_service(db: AsyncSession) -> EditAccessService:
    return EditAccessService(
        ticket_repository=TicketRepository(db),
        user_repository=UserRepository(db),
        interaction_repository=InteractionRepository(db),
        edit_access_repository=TicketEditAccessRequestRepository(db),
        notification_service=NotificationService(NotificationRepository(db)),
    )


@router.post(
    "/{ticket_id}/edit-access/request",
    response_model=EditAccessRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_edit_access(
    ticket_id: UUID,
    request: EditAccessRequestCreate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Asks to work a ticket you're not the assigned agent on and don't
    already hold ticket:editother_ticket for. Reviewed by anyone who does.
    """

    service = _get_edit_access_service(db)

    return await service.request_access(
        ticket_id=ticket_id,
        request=request,
        current_user=current_user,
    )


@router.get(
    "/{ticket_id}/edit-access",
    response_model=list[EditAccessRequestResponse],
    status_code=status.HTTP_200_OK,
)
async def list_edit_access_requests(
    ticket_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns every edit-access request on this ticket, newest first."""

    service = _get_edit_access_service(db)

    return await service.list_for_ticket(ticket_id, current_user=current_user)


@router.post(
    "/{ticket_id}/edit-access/{request_id}/approve",
    response_model=EditAccessRequestResponse,
    status_code=status.HTTP_200_OK,
)
async def approve_edit_access(
    ticket_id: UUID,
    request_id: UUID,
    request: EditAccessApproveRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Approves a pending edit-access request. Requires ticket:editother_ticket
    yourself — the same permission this grants the requester.
    """

    service = _get_edit_access_service(db)

    return await service.approve(
        ticket_id=ticket_id,
        request_id=request_id,
        request=request,
        current_user=current_user,
    )


@router.post(
    "/{ticket_id}/edit-access/{request_id}/reject",
    response_model=EditAccessRequestResponse,
    status_code=status.HTTP_200_OK,
)
async def reject_edit_access(
    ticket_id: UUID,
    request_id: UUID,
    request: EditAccessRejectRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """Rejects a pending edit-access request."""

    service = _get_edit_access_service(db)

    return await service.reject(
        ticket_id=ticket_id,
        request_id=request_id,
        request=request,
        current_user=current_user,
    )
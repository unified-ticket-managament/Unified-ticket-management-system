from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db

from app.repositories.attachment_repository import (
    AttachmentRepository,
)
from app.repositories.audit_log_repository import (
    AuditLogRepository,
)
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.ticket_repository import (
    TicketRepository,
)
from app.repositories.user_repository import UserRepository

from app.schemas.attach_interaction import (
    AttachInteractionRequest,
    AttachInteractionResponse,
)
from app.schemas.attachment import (
    AttachmentUploadResponse,
)
from app.schemas.audit_log import AuditLogResponse
from app.schemas.interaction import (
    HideInteractionRequest,
    HideInteractionResponse,
    InteractionResponse,
)
from app.schemas.note import (
    InternalNoteCreate,
    InternalNoteResponse,
)
from app.schemas.ticket import TicketResponse, TicketUpdate
from app.schemas.ticket_action import (
    PriorityChangeRequest,
    ReplyCreate,
    ResolveTicketRequest,
    StatusChangeRequest,
    TicketActionResponse,
    TransferAgentRequest,
)
from app.schemas.ticket_from_interaction import (
    TicketFromInteractionCreate,
    TicketFromInteractionResponse,
)

from app.services.attachment_service import AttachmentService
from app.services.inbox_ticket_service import InboxTicketService
from app.services.interaction_service import InteractionService
from app.services.ticket_service import TicketService
from app.storage import get_storage_service

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
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new ticket from a pending inbox interaction.
    """

    ticket_repository = TicketRepository(db)
    interaction_repository = InteractionRepository(db)

    service = InboxTicketService(
        ticket_repository=ticket_repository,
        interaction_repository=interaction_repository,
    )

    return await service.create_ticket_from_interaction(request)


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
    db: AsyncSession = Depends(get_db),
):

    ticket_repository = TicketRepository(db)
    interaction_repository = InteractionRepository(db)

    service = InboxTicketService(
        ticket_repository=ticket_repository,
        interaction_repository=interaction_repository,
    )

    return await service.attach_to_existing_ticket(
        ticket_id=ticket_id,
        request=request,
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
    agent_name: str | None = Query(
        default=None,
        description=(
            "The agent viewing this timeline. If provided and the "
            "ticket is assigned to someone else, returns 403."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)
    attachment_repository = AttachmentRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
        attachment_repository=attachment_repository,
        storage_service=get_storage_service(),
    )

    return await service.get_ticket_interactions(ticket_id, agent_name=agent_name)


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
    agent_name: str | None = Query(
        default=None,
        description=(
            "The agent viewing this audit trail. If provided and the "
            "ticket is assigned to someone else, returns 403."
        ),
    ),
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

    return await service.get_ticket_audit_logs(ticket_id, agent_name=agent_name)


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
    agent_name: str | None = Query(
        default=None,
        description="The agent adding this note. Recorded as the audit actor.",
    ),
    db: AsyncSession = Depends(get_db),
):

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
    )

    return await service.add_internal_note(
        ticket_id=ticket_id,
        request=request,
        agent_name=agent_name,
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
    agent_name: str | None = Query(
        default=None,
        description="The agent sending this reply. Recorded as the audit actor.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Sends a reply to the client on this ticket.

    Stored as an OUTBOUND interaction on the
    ticket timeline.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
    )

    return await service.add_reply(
        ticket_id=ticket_id,
        request=request,
        agent_name=agent_name,
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
    agent_name: str | None = Query(
        default=None,
        description="The agent making this change. Recorded as the audit actor.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Changes the ticket's status and records the
    change as an interaction on the timeline.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
    )

    return await service.change_status(
        ticket_id=ticket_id,
        request=request,
        agent_name=agent_name,
    )


# =========================================================
# Resolve Ticket
# =========================================================

@router.post(
    "/{ticket_id}/resolve",
    response_model=TicketActionResponse,
    status_code=status.HTTP_200_OK,
)
async def resolve_ticket(
    ticket_id: UUID,
    request: ResolveTicketRequest,
    agent_name: str | None = Query(
        default=None,
        description="The agent resolving this ticket. Recorded as the audit actor.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Marks the ticket resolved and closed, recording the
    change as an interaction on the timeline and on the
    audit trail.
    """

    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
    )

    return await service.resolve_ticket(
        ticket_id=ticket_id,
        request=request,
        agent_name=agent_name,
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
    agent_name: str | None = Query(
        default=None,
        description="The agent making this change. Recorded as the audit actor.",
    ),
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
    )

    return await service.change_priority(
        ticket_id=ticket_id,
        request=request,
        agent_name=agent_name,
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
    agent_name: str | None = Form(
        default=None,
        description="The agent uploading these files. Recorded as the audit actor.",
    ),
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
    user_repository = UserRepository(db)

    service = AttachmentService(
        attachment_repository=attachment_repository,
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        storage_service=get_storage_service(),
        user_repository=user_repository,
    )

    return await service.upload_attachment(
        ticket_id=ticket_id,
        files=files,
        agent_name=agent_name,
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
    agent_name: str | None = Query(
        default=None,
        description="The agent hiding this interaction. Recorded as the audit actor.",
    ),
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
        agent_name=agent_name,
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
    agent_name: str | None = Query(
        default=None,
        description="The agent making this transfer. Recorded as the audit actor.",
    ),
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
    )

    return await service.transfer_agent(
        ticket_id=ticket_id,
        request=request,
        agent_name=agent_name,
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
    agent_name: str | None = Query(
        default=None,
        description="The agent making this change. Recorded as the audit actor.",
    ),
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

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
    )

    return await service.update(
        ticket_id=ticket_id,
        request=request,
        agent_name=agent_name,
    )


# =========================================================
# List Tickets
# =========================================================

@router.get(
    "",
    response_model=list[TicketResponse],
    status_code=status.HTTP_200_OK,
)
async def list_tickets(
    agent_name: str | None = Query(
        default=None,
        description=(
            "Restrict results to tickets assigned to this agent "
            "(unassigned tickets are always included). Omit to "
            "return every ticket."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns tickets, most recently created first.
    """

    ticket_repository = TicketRepository(db)
    user_repository = UserRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
    )

    return await service.list_all(agent_name=agent_name)


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
    agent_name: str | None = Query(
        default=None,
        description=(
            "The agent viewing this ticket. If provided and the "
            "ticket is assigned to someone else, returns 403."
        ),
    ),
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

    service = TicketService(
        ticket_repository=ticket_repository,
        user_repository=user_repository,
    )

    return await service.get_by_id(ticket_id, agent_name=agent_name)
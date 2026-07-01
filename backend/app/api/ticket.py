from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db

from app.repositories.attachment_repository import (
    AttachmentRepository,
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
    AttachmentUploadRequest,
    AttachmentUploadResponse,
)
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

    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
        user_repository=user_repository,
    )

    return await service.get_ticket_interactions(ticket_id, agent_name=agent_name)


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
    request: AttachmentUploadRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Uploads a file to this ticket.

    Recorded as an interaction on the timeline,
    with the file metadata stored separately.
    """

    attachment_repository = AttachmentRepository(db)
    interaction_repository = InteractionRepository(db)
    ticket_repository = TicketRepository(db)

    service = AttachmentService(
        attachment_repository=attachment_repository,
        interaction_repository=interaction_repository,
        ticket_repository=ticket_repository,
    )

    return await service.upload_attachment(
        ticket_id=ticket_id,
        request=request,
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
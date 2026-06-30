from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db

from app.repositories.ticket_repository import (
    TicketRepository,
)
from app.repositories.interaction_repository import (
    InteractionRepository,
)

from app.schemas.ticket import TicketResponse
from app.schemas.interaction import InteractionResponse
from app.schemas.ticket_from_interaction import (
    TicketFromInteractionCreate,
    TicketFromInteractionResponse,
)
from app.schemas.attach_interaction import (
    AttachInteractionRequest,
    AttachInteractionResponse,
)

from app.services.ticket_service import (
    TicketService,
)
from app.services.interaction_service import (
    InteractionService,
)
from app.services.inbox_ticket_service import (
    InboxTicketService,
)

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

    ticket_repository = TicketRepository(db)

    interaction_repository = InteractionRepository(db)

    service = InboxTicketService(
        ticket_repository=ticket_repository,
        interaction_repository=interaction_repository,
    )

    return await service.create_ticket_from_interaction(
        request
    )


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
    db: AsyncSession = Depends(get_db),
):

    interaction_repository = InteractionRepository(db)

    service = InteractionService(
        interaction_repository=interaction_repository,
    )

    return await service.get_ticket_interactions(
        ticket_id
    )


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
    db: AsyncSession = Depends(get_db),
):

    ticket_repository = TicketRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
    )

    return await service.get_by_id(
        ticket_id
    )
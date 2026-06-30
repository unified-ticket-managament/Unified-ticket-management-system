from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.ticket_repository import (
    TicketRepository,
)
from app.schemas.ticket_from_interaction import (
    TicketFromInteractionCreate,
    TicketFromInteractionResponse,
)
from app.services.inbox_ticket_service import (
    InboxTicketService,
)

from app.services.interaction_service import (
    InteractionService,
)
from app.schemas.interaction import (
    InteractionResponse,
)

from app.services.ticket_service import (
    TicketService,
)

from app.schemas.ticket import (
    TicketResponse,
)

router = APIRouter(
    prefix="/tickets",
    tags=["Tickets"],
)


@router.post(
    "/from-interaction",
    response_model=TicketFromInteractionResponse,
    status_code=201,
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

    return await service.create_ticket_from_interaction(
        request
    )

# ---------------------------------------------------------
# Get Ticket Details
# ---------------------------------------------------------

@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    status_code=status.HTTP_200_OK,
)
async def get_ticket(
    ticket_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns ticket details.

    This endpoint returns only the ticket metadata.
    Ticket interactions (timeline) are retrieved
    using a separate endpoint.
    """

    ticket_repository = TicketRepository(db)

    service = TicketService(
        ticket_repository=ticket_repository,
    )

    return await service.get_by_id(
        ticket_id
    )



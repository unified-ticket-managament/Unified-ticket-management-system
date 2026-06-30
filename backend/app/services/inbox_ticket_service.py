from fastapi import HTTPException, status

from app.enums import InteractionStatus
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.ticket_repository import (
    TicketRepository,
)
from app.schemas.payloads import EmailPayload
from app.schemas.ticket import TicketCreate
from app.schemas.ticket_from_interaction import (
    TicketFromInteractionCreate,
    TicketFromInteractionResponse,
)


class InboxTicketService:
    """
    Workflow service responsible for creating
    a ticket from an inbox interaction.
    """

    def __init__(
        self,
        ticket_repository: TicketRepository,
        interaction_repository: InteractionRepository,
    ):
        self.ticket_repository = ticket_repository
        self.interaction_repository = interaction_repository

    async def create_ticket_from_interaction(
        self,
        request: TicketFromInteractionCreate,
    ) -> TicketFromInteractionResponse:

        # ----------------------------------------
        # Load interaction
        # ----------------------------------------

        interaction = await self.interaction_repository.get_by_id(
            request.interaction_id
        )

        if interaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        # ----------------------------------------
        # Validation
        # ----------------------------------------

        if interaction.ticket_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Interaction already belongs to a ticket.",
            )

        if interaction.status != InteractionStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Interaction is not pending.",
            )

        # ----------------------------------------
        # Read Email Payload
        # ----------------------------------------

        payload = EmailPayload.model_validate(
            interaction.payload
        )

        # ----------------------------------------
        # Create Ticket
        # ----------------------------------------

        ticket = await self.ticket_repository.create(

            TicketCreate(

                client_id=payload.client_id,

                agent_id=payload.agent_id,

                title=request.title,

                ticket_type=request.ticket_type,

                current_priority=request.current_priority,

                custom_fields={},

            )

        )

        # ----------------------------------------
        # Attach interaction to ticket
        # ----------------------------------------

        await self.interaction_repository.assign_to_ticket(

            interaction=interaction,

            ticket_id=ticket.ticket_id,

        )

        # ----------------------------------------
        # Return
        # ----------------------------------------

        return TicketFromInteractionResponse(

            message="Ticket created successfully.",

            ticket_id=ticket.ticket_id,

            interaction_id=interaction.interaction_id,

            status=InteractionStatus.ASSIGNED.value,

        )
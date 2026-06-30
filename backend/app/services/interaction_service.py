# interaction_service.py


from uuid import UUID

from fastapi import HTTPException, status

from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.schemas.interaction import (
    InteractionCreate,
    InteractionResponse,
    InteractionUpdate,
)

from app.enums import (
    InteractionDirection,
    InteractionStatus,
)

from app.schemas.note import (
    InternalNoteCreate,
    InternalNoteResponse,
)


from app.repositories.ticket_repository import (
    TicketRepository,
)

from typing import Any
from app.models.interaction import Interaction


class InteractionService:
    """
    Service layer for Interaction operations.
    """

    def __init__(
        self,
        interaction_repository: InteractionRepository,
        ticket_repository: TicketRepository,
    ):
        self.interaction_repository = interaction_repository
        self.ticket_repository = ticket_repository

    # ---------------------------------------------------------
    # Create Interaction
    # ---------------------------------------------------------

    async def create(
        self,
        request: InteractionCreate,
    ) -> InteractionResponse:

        interaction = await self.interaction_repository.create(
            request
        )

        return InteractionResponse.model_validate(
            interaction
        )

    # ---------------------------------------------------------
    # Get Interaction By ID
    # ---------------------------------------------------------

    async def get_by_id(
        self,
        interaction_id: UUID,
    ) -> InteractionResponse:

        interaction = await self.interaction_repository.get_by_id(
            interaction_id
        )

        if interaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        return InteractionResponse.model_validate(
            interaction
        )

    # ---------------------------------------------------------
    # Update Interaction
    # ---------------------------------------------------------

    async def update(
        self,
        interaction_id: UUID,
        request: InteractionUpdate,
    ) -> InteractionResponse:

        interaction = await self.interaction_repository.get_by_id(
            interaction_id
        )

        if interaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Interaction not found.",
            )

        interaction = await self.interaction_repository.update(
            interaction,
            request,
        )

        return InteractionResponse.model_validate(
            interaction
        )

    # ---------------------------------------------------------
    # Ticket Timeline
    # ---------------------------------------------------------

    async def get_ticket_interactions(
        self,
        ticket_id: UUID,
    ) -> list[InteractionResponse]:
        """
        Returns the complete timeline for a ticket.

        Interactions are ordered chronologically
        by created_at (oldest first).
        """

        interactions = (
            await self.interaction_repository
            .list_by_ticket_id(ticket_id)
        )

        return [
            InteractionResponse.model_validate(
                interaction
            )
            for interaction in interactions
        ]

    


# ---------------------------------------------------------
# Shared Helper
# ---------------------------------------------------------

    async def _create_ticket_interaction(
        self,
        *,
        ticket_id: UUID,
        interaction_type: str,
        direction: InteractionDirection,
        payload: dict[str, Any],
        performed_by: UUID | None = None,
        status: InteractionStatus = InteractionStatus.ASSIGNED,
    ) -> Interaction:
        """
        Creates any interaction that belongs to a ticket.

        Used by:
        - Reply
        - Internal Note
        - Status Change
        - Priority Change
        - Assignment Change
        - Attachments
        """

        # Validate ticket
        ticket = await self.ticket_repository.get_by_id(ticket_id)

        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )

        interaction = await self.interaction_repository.create(

            InteractionCreate(

                ticket_id=ticket_id,

                interaction_type=interaction_type,

                direction=direction,

                status=status,

                performed_by=performed_by,

                payload=payload,

                is_visible=True,

                message_id=None,

            )

        )

        return interaction
    # ---------------------------------------------------------
# Internal Note
# ---------------------------------------------------------

    async def add_internal_note(
        self,
        ticket_id: UUID,
        request: InternalNoteCreate,
    ) -> InternalNoteResponse:
        """
        Adds an internal note to a ticket.

        Every internal note is stored as an Interaction.
        """

        # -------------------------------------------------
        # Validate ticket
        # -------------------------------------------------

        

        # -------------------------------------------------
        # Create interaction
        # -------------------------------------------------

        interaction = await self._create_ticket_interaction(
            ticket_id=ticket_id,
            interaction_type="INTERNAL_NOTE",
            direction=InteractionDirection.INTERNAL,
            payload={
                "note": request.note,
            },
        )

        # -------------------------------------------------
        # Response
        # -------------------------------------------------

        return InternalNoteResponse(

            interaction_id=interaction.interaction_id,

            ticket_id=ticket_id,

            message="Internal note added successfully.",

            created_at=interaction.created_at,

        )    
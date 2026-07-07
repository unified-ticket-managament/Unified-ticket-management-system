from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import TicketCategory, TicketPriority


class TicketFromInteractionCreate(BaseModel):
    """
    Request schema used when an agent creates
    a new ticket from an inbox interaction.
    """

    interaction_id: UUID

    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )

    ticket_type: TicketCategory

    current_priority: TicketPriority = TicketPriority.MEDIUM


class TicketFromInteractionResponse(BaseModel):
    """
    Response returned after successfully creating
    a ticket from an interaction.
    """

    message: str

    ticket_id: UUID

    interaction_id: UUID

    status: str
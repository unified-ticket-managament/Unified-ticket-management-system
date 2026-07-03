from uuid import UUID

from pydantic import BaseModel

from app.enums import InteractionStatus


class AttachInteractionRequest(BaseModel):
    """
    Request to attach a pending inbox interaction
    to an existing ticket.
    """

    interaction_id: UUID


class AttachInteractionResponse(BaseModel):
    """
    Response returned after successfully attaching
    an interaction to an existing ticket.
    """

    message: str

    ticket_id: UUID

    interaction_id: UUID

    status: InteractionStatus
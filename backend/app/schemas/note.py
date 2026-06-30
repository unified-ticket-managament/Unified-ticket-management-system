from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMBase


class InternalNoteCreate(BaseModel):
    """
    Request body for adding an internal note
    to an existing ticket.
    """

    note: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Internal note visible only to agents.",
    )


class InternalNoteResponse(ORMBase):
    """
    Response returned after successfully
    creating an internal note.
    """

    interaction_id: UUID
    ticket_id: UUID
    message: str
    created_at: datetime
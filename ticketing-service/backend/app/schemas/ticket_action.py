from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import TicketPriority, TicketStatus
from app.schemas.common import ORMBase

#ticket_action.py
class ReplyCreate(BaseModel):
    """
    Request body for replying to a client on a ticket.
    """

    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Reply visible to the client.",
    )


class InteractionReplyRequest(BaseModel):
    """
    Request body for replying to a client on a bare (not-yet-
    ticketed) inbox interaction — the "general communication, no
    ticket needed" path.
    """

    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Reply visible to the client.",
    )


class InteractionReplyResponse(ORMBase):
    """
    Response returned after replying to a bare interaction.
    """

    interaction_id: UUID
    parent_interaction_id: UUID
    message: str
    created_at: datetime


class StatusChangeRequest(BaseModel):
    """
    Request body for changing a ticket's status.
    """

    new_status: TicketStatus


class PriorityChangeRequest(BaseModel):
    """
    Request body for changing a ticket's priority.
    """

    new_priority: TicketPriority


class TransferAgentRequest(BaseModel):
    """
    Request body for transferring full ownership of a ticket
    from its current agent to a different active Staff member.
    """

    new_agent_id: UUID


class TicketActionResponse(ORMBase):
    """
    Generic response returned after an action
    (reply, status change, priority change) creates
    a new interaction on a ticket.
    """

    interaction_id: UUID
    ticket_id: UUID
    message: str
    created_at: datetime
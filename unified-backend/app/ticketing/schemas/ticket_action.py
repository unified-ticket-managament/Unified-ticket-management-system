from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.ticketing.enums import TicketPriority, TicketStatus
from app.ticketing.schemas.common import ORMBase

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

    # Additional recipients beyond the client's original sender — the
    # Account Manager's own Cc is still auto-added on top of these
    # (see InteractionService._resolve_account_manager_email), not
    # replaced by them.
    cc: list[EmailStr] = Field(default_factory=list)

    bcc: list[EmailStr] = Field(default_factory=list)

    # Overrides the recipient the envelope would otherwise default to
    # (the ticket's latest inbound sender) — lets an agent pick any
    # personal address this client has previously contacted the
    # shared inbox from, via the "To" dropdown, instead of always
    # replying to whoever happened to send the most recent message.
    # None means "use the default".
    to_email: EmailStr | None = None


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

    cc: list[EmailStr] = Field(default_factory=list)

    bcc: list[EmailStr] = Field(default_factory=list)

    # See ReplyCreate.to_email above — same override, same reason.
    to_email: EmailStr | None = None


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
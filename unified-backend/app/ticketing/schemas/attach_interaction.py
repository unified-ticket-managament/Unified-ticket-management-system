from uuid import UUID

from pydantic import BaseModel

from app.ticketing.enums import InteractionStatus, TicketPriority


class AttachInteractionRequest(BaseModel):
    """
    Request to attach a pending inbox interaction
    to an existing ticket.

    `new_agent_id`/`new_priority` are only applied when the target
    ticket is CLOSED (i.e. this attach is also reopening it) — see
    InboxTicketService.attach_to_existing_ticket. Omit both to keep
    the existing assignee/priority on reopen.
    """

    interaction_id: UUID

    new_agent_id: UUID | None = None

    new_priority: TicketPriority | None = None


class AttachInteractionResponse(BaseModel):
    """
    Response returned after successfully attaching
    an interaction to an existing ticket.
    """

    message: str

    ticket_id: UUID

    interaction_id: UUID

    status: InteractionStatus

    ticket_reopened: bool = False
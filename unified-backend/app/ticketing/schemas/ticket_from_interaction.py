from uuid import UUID

from pydantic import BaseModel, Field

from app.ticketing.enums import TicketPriority


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

    # Category name from the RBAC-owned `categories` table — see
    # TicketCreate.ticket_type's comment in schemas/ticket.py.
    ticket_type: str = Field(..., min_length=1, max_length=100)

    current_priority: TicketPriority = TicketPriority.MEDIUM

    # Who the ticket should be assigned to — the Create Ticket dialog's
    # "Assigned To" picker. None (the default, and the only value any
    # pre-existing caller ever sent) preserves the original behavior:
    # the ticket is born unclaimed and sits in the shared pool. When
    # set, InboxTicketService.create_ticket_from_interaction validates
    # it against AssignmentService's own hierarchy rules for the
    # caller's role before applying it — never trusted as-is.
    agent_id: UUID | None = None


class TicketFromInteractionResponse(BaseModel):
    """
    Response returned after successfully creating
    a ticket from an interaction.
    """

    message: str

    ticket_id: UUID

    interaction_id: UUID

    status: str
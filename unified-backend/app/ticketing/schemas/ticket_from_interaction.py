from uuid import UUID

from pydantic import BaseModel, Field

from app.ticketing.enums import TicketPriority


class AdditionalAssignmentIn(BaseModel):
    """One extra (SECONDARY) assignee, picked FOR a specific category."""

    category_name: str = Field(..., min_length=1, max_length=150)
    user_id: UUID


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

    # Multi-assignment: extra (SECONDARY) assignees chosen in the same
    # Create Ticket dialog. Requires agent_id (the primary). Each one is
    # validated against the same hierarchy rule as agent_id, plus
    # TicketAssignmentService's own eligibility/RBAC checks — and the
    # ticket is created with all of them or not at all.
    additional_agent_ids: list[UUID] = Field(default_factory=list, max_length=50)

    # Same as additional_agent_ids, but each person is picked for a
    # specific category (validated against THAT category's hierarchy),
    # and the ticket also joins every category listed here.
    additional_assignments: list[AdditionalAssignmentIn] = Field(
        default_factory=list, max_length=50
    )


class TicketFromInteractionResponse(BaseModel):
    """
    Response returned after successfully creating
    a ticket from an interaction.
    """

    message: str

    ticket_id: UUID

    interaction_id: UUID

    status: str
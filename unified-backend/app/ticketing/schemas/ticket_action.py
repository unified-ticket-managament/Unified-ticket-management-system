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

    # Points at an interaction that already has real, stored
    # attachments — in practice, the interaction_id a preceding
    # POST /tickets/{id}/attachments upload just returned. Set this so
    # those files are embedded in the actual outbound email, not just
    # recorded on the ticket's own timeline (see InteractionService.
    # add_reply). None (the default) sends with no attachments,
    # exactly as before this field existed.
    attachment_source_interaction_id: UUID | None = None

    # When the message being replied to arrived via Microsoft Graph,
    # selects Graph's native replyAll action (Cc'ing everyone on the
    # original thread) instead of reply — mirrors the Mail page's own
    # Reply/Reply All toggle. Ignored (falls back to plain sendMail)
    # when Graph's own message id for the original message isn't
    # known — see build_reply_envelope's reply_to_provider_message_id.
    reply_all: bool = False


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

    # See ReplyCreate.reply_all above — same meaning, same reason.
    reply_all: bool = False


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
    from its current agent to a different active, agent-capable
    user (any role — see AGENT_ROLE_NAMES).
    """

    new_agent_id: UUID

    reason: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Why the ticket is being transferred, recorded on the audit log.",
    )

    category_name: str | None = Field(
        default=None,
        description=(
            "Optional — the category the caller filtered the picker to. "
            "When present, the backend re-validates new_agent_id actually "
            "belongs to it, rather than trusting the frontend filter. "
            "When it also differs from the ticket's own current "
            "ticket_type, this becomes a cross-category transfer: the "
            "ticket's category is moved to it (recorded as a separate "
            "CATEGORY_TRANSFERRED audit entry) in the same request that "
            "reassigns the agent."
        ),
    )


class TicketActionResponse(ORMBase):
    """
    Generic response returned after a ticket-mutating action. Reply
    still creates a real Interaction row, so `interaction_id` is
    populated there — status/priority/transfer/claim no longer create
    one (see services/audit_to_interaction.py), so it's `None` for
    those.
    """

    interaction_id: UUID | None
    ticket_id: UUID
    message: str
    created_at: datetime


class CancelSendResponse(ORMBase):
    """
    Response for POST /interactions/{id}/cancel-send (Issue 8's Undo
    action) — a near-twin of TicketActionResponse, but with `ticket_id`
    genuinely optional: unlike every other ticket-mutating action, this
    one is reachable for a still-pending pre-ticket Compose/reply too
    (interaction.ticket_id is None until/unless that thread is later
    turned into a ticket), so this can't reuse TicketActionResponse's
    own required `ticket_id`.
    """

    interaction_id: UUID
    ticket_id: UUID | None
    message: str
    created_at: datetime
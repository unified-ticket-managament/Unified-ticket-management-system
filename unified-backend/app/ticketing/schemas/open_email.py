from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.ticketing.enums import InteractionStatus
from app.ticketing.schemas.attachment import AttachmentMetadata
from app.ticketing.schemas.interaction import InteractionResponse


class OpenEmailResponse(BaseModel):
    """
    Response returned when an Account Manager (or agent) opens an
    email from the inbox — the root of a conversation, plus every
    reply/follow-up already filed under it.
    """

    interaction_id: UUID

    ticket_id: UUID | None

    client_id: UUID | None

    client_name: str

    to_email: str | None

    from_email: str | None

    from_name: str | None

    # Only ever non-empty on a Compose-authored root — an inbound
    # email has no Cc/Bcc of its own (see EmailPayload's matching
    # fields).
    cc: list[str] = Field(default_factory=list)

    bcc: list[str] = Field(default_factory=list)

    subject: str

    body: str

    message_id: str | None

    received_at: datetime

    status: InteractionStatus

    claimed_by: UUID | None = None

    claimed_by_name: str | None = None

    # Resolved via the client's account_manager_id — who owns this
    # client relationship (distinct from claimed_by, "who's working
    # this item right now").
    account_manager_name: str | None = None

    # Only meaningful once this item has become a ticket — a
    # pre-ticket Interaction has neither a priority nor a category
    # (category is chosen at ticket-creation time). None pre-ticket.
    ticket_priority: str | None = None

    ticket_category: str | None = None

    # Lets the Mail inbox's own reply composer disable/hide itself on
    # a closed ticket without a failed round-trip — the backend's
    # ensure_ticket_not_closed (called from add_reply) is still the
    # real enforcement, this is just so the UI doesn't need to guess.
    ticket_status: str | None = None

    tags: list[str] = Field(default_factory=list)

    folder_id: UUID | None = None

    snoozed_until: datetime | None = None

    # The requesting user's own saved-but-unsent draft reply on this
    # thread, if any — lets the reply composer prefill/resume it.
    # None both when there's no draft and when the thread is already
    # ticketed (drafts are pre-ticket only).
    draft_message: str | None = None

    draft_cc: list[str] = Field(default_factory=list)

    draft_bcc: list[str] = Field(default_factory=list)

    # Already-uploaded attachments on the draft itself (a separate
    # interaction row from this root) — distinct from `attachments`
    # below, which is the root email's own attachments.
    draft_attachments: list[AttachmentMetadata] = Field(default_factory=list)

    attachments: list[AttachmentMetadata] = Field(default_factory=list)

    replies: list[InteractionResponse] = Field(default_factory=list)

    # "Attach to Existing Ticket" convenience — populated when the
    # thread's own headers (or an already-ticketed reply within it)
    # let us infer which ticket this is probably about, so the
    # Account Manager isn't stuck pasting a ticket_id from memory.
    # None means "no confident guess", not an error — the normal
    # manual search/paste flow still works either way.
    recommended_ticket_id: UUID | None = None

    recommended_ticket_reason: str | None = None

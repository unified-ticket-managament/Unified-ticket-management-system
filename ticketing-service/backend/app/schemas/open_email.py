from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import InteractionStatus
from app.schemas.attachment import AttachmentMetadata
from app.schemas.interaction import InteractionResponse


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

    tags: list[str] = Field(default_factory=list)

    folder_id: UUID | None = None

    snoozed_until: datetime | None = None

    # The requesting user's own saved-but-unsent draft reply on this
    # thread, if any — lets the reply composer prefill/resume it.
    # None both when there's no draft and when the thread is already
    # ticketed (drafts are pre-ticket only).
    draft_message: str | None = None

    attachments: list[AttachmentMetadata] = Field(default_factory=list)

    replies: list[InteractionResponse] = Field(default_factory=list)

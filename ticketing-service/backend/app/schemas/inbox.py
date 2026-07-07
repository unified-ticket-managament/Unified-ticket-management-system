from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.enums import InteractionDirection, InteractionStatus


class InboxItemResponse(BaseModel):
    """
    Represents one email shown in the Account Manager inbox.

    Only summary information is returned. The full email content
    (and its replies) is retrieved using the thread-detail endpoint.
    """

    interaction_id: UUID

    client_id: UUID | None

    client_name: str

    from_email: str | None

    to_email: str | None

    subject: str

    message_id: str | None

    received_at: datetime

    status: InteractionStatus

    direction: InteractionDirection

    # Set when this root email was promoted to (or attached onto) a
    # ticket — populated in the "ticketed" and "all" views so those
    # rows can link straight to the ticket.
    ticket_id: UUID | None = None

    has_attachments: bool = False

    # Set once someone claims this item via "Assign to me" — None
    # means unclaimed. Useful in the "all inboxes" supervisor view to
    # see who on the team has already picked something up.
    claimed_by: UUID | None = None
    claimed_by_name: str | None = None


class InboxResponse(BaseModel):
    """
    Account Manager Inbox Response.
    """

    total: int

    items: list[InboxItemResponse]

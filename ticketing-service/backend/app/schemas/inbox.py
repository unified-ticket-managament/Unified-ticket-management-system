from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.enums import InteractionStatus


class InboxItemResponse(BaseModel):
    """
    Represents one email shown in the
    Agent Inbox.

    Only summary information is returned.
    The full email content is retrieved
    using the Email Details endpoint.
    """

    interaction_id: UUID

    client_name: str

    subject: str

    message_id: str | None

    received_at: datetime

    status: InteractionStatus

    has_attachments: bool = False


class InboxResponse(BaseModel):
    """
    Agent Inbox Response.
    """

    total: int

    items: list[InboxItemResponse]
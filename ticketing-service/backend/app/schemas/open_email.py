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

    attachments: list[AttachmentMetadata] = Field(default_factory=list)

    replies: list[InteractionResponse] = Field(default_factory=list)

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.ticketing.schemas.attachment import AttachmentMetadata

#compose.py

class ComposeEmailRequest(BaseModel):
    """
    Request body for POST /inbox/compose — authoring a brand-new
    outbound email to one of the platform's clients. Distinct from
    ReplyCreate/InteractionReplyRequest because there is no existing
    interaction to reply onto yet; `to_email` is the external
    recipient the agent typed in themselves rather than a sender
    resolved from an inbound email.
    """

    client_id: UUID

    to_email: EmailStr

    cc: list[EmailStr] = Field(default_factory=list)

    bcc: list[EmailStr] = Field(default_factory=list)

    subject: str = Field(..., min_length=1, max_length=500)

    message: str = Field(..., min_length=1, max_length=20000)


class ComposeEmailResponse(BaseModel):
    """Response returned after a new Compose email is recorded."""

    interaction_id: UUID

    client_id: UUID

    created_at: datetime

    attachments: list[AttachmentMetadata] = Field(default_factory=list)

    message: str = "Email sent successfully."

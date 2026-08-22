from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator

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

    `to_email` is optional — the primary/only recipient can instead
    come entirely from `distribution_list_ids` (Compose has no fixed
    thread, so a picked Distribution List becomes a genuine additional
    "To" recipient, not downgraded to Cc — resolved server-side and
    merged via the same additive OutboundEnvelope.to_emails mechanism
    Forward uses). At least one of the two must be present.
    """

    client_id: UUID

    to_email: EmailStr | None = None

    distribution_list_ids: list[UUID] = Field(default_factory=list)

    cc: list[EmailStr] = Field(default_factory=list)

    bcc: list[EmailStr] = Field(default_factory=list)

    subject: str = Field(..., min_length=1, max_length=500)

    message: str = Field(..., min_length=1, max_length=20000)

    # Optional sanitized-on-the-backend HTML counterpart to `message`
    # (Outlook-style clipboard paste). See ReplyCreate.body_html
    # (schemas/ticket_action.py) for the same additive contract.
    body_html: str | None = None

    @model_validator(mode="after")
    def _require_a_recipient_source(self) -> "ComposeEmailRequest":
        if not self.to_email and not self.distribution_list_ids:
            raise ValueError("Either to_email or distribution_list_ids is required.")
        return self


class ComposeEmailResponse(BaseModel):
    """Response returned after a new Compose email is recorded."""

    interaction_id: UUID

    client_id: UUID

    created_at: datetime

    attachments: list[AttachmentMetadata] = Field(default_factory=list)

    message: str = "Email sent successfully."

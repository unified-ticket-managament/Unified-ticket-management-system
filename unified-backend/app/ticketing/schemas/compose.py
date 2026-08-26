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
    come entirely from `to_emails` (multiple manually-typed addresses —
    see below) and/or `distribution_list_ids` (Compose has no fixed
    thread, so a picked Distribution List becomes a genuine additional
    "To" recipient, not downgraded to Cc — resolved server-side and
    merged via the same additive OutboundEnvelope.to_emails mechanism
    Forward uses). At least one of the three must be present.

    `to_emails` additively carries every "To" address past the first
    when the caller has more than one manually-typed recipient (the
    frontend used to have no way to express this and downgraded every
    extra "To" entry into Cc instead — a real, reported bug, since the
    outbound Graph message and the persisted Sent record both ended up
    with the wrong To/Cc split). `to_email` is kept, unchanged, for
    backward compatibility with the single-recipient case; compose_email
    merges both into one effective "To" list before resolving Distribution
    Lists on top.

    Exactly one of `client_id`/`category_id` must be given — the
    "From" mailbox this message sends as. `category_id` sends from a
    CATEGORY's own shared mailbox (Category.inbox_email) instead of a
    client's, mirroring the mutual-exclusivity OutgoingEmailRequest
    (schemas/mail_integration.py) already uses for client_id/from_email.
    """

    client_id: UUID | None = None

    category_id: UUID | None = None

    to_email: EmailStr | None = None

    to_emails: list[EmailStr] = Field(default_factory=list)

    distribution_list_ids: list[UUID] = Field(default_factory=list)

    cc: list[EmailStr] = Field(default_factory=list)

    bcc: list[EmailStr] = Field(default_factory=list)

    subject: str = Field(..., min_length=1, max_length=500)

    message: str = Field(..., min_length=1, max_length=20000)

    # Optional sanitized-on-the-backend HTML counterpart to `message`
    # (Outlook-style clipboard paste). See ReplyCreate.body_html
    # (schemas/ticket_action.py) for the same additive contract.
    body_html: str | None = None

    # Client-generated Send idempotency key — see ReplyCreate.
    # idempotency_key's own docstring for the contract. None (the
    # default) opts out entirely, exactly like every Compose before
    # this field existed.
    idempotency_key: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _require_a_recipient_source(self) -> "ComposeEmailRequest":
        if not self.to_email and not self.to_emails and not self.distribution_list_ids:
            raise ValueError(
                "At least one of to_email, to_emails, or distribution_list_ids is required."
            )
        return self

    @model_validator(mode="after")
    def _require_exactly_one_sender(self) -> "ComposeEmailRequest":
        if (self.client_id is None) == (self.category_id is None):
            raise ValueError("Exactly one of client_id or category_id must be provided.")
        return self


class ComposeDraftSaveRequest(BaseModel):
    """
    Request body for creating/updating a brand-new Compose message's
    server-side draft (POST /inbox/compose-draft, PUT /inbox/compose-
    draft/{interaction_id}). Unlike DraftSaveRequest (a pre-ticket
    Reply draft, which always has an existing thread root to borrow
    client_id/category_id/recipient context from), a Compose draft has
    no such thread — every field the eventual send needs must live on
    the draft itself. Every field is optional/defaulted so an entirely
    empty draft (Compose just opened, nothing typed yet) is a valid
    save — this mirrors ComposeEmailRequest's own field set, minus its
    "at least one recipient source" validator, which would wrongly
    reject a legitimate in-progress empty draft.
    """

    client_id: UUID | None = None
    category_id: UUID | None = None
    to_email: EmailStr | None = None
    to_emails: list[EmailStr] = Field(default_factory=list)
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)
    subject: str = ""
    message: str = ""
    body_html: str | None = None


class ComposeDraftResponse(BaseModel):
    """Everything needed to fully restore a Compose draft's form on reopen."""

    interaction_id: UUID
    client_id: UUID | None = None
    category_id: UUID | None = None
    to_email: str | None = None
    to_emails: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str = ""
    message: str = ""
    body_html: str | None = None
    attachments: list[AttachmentMetadata] = Field(default_factory=list)
    created_at: datetime


class ComposeEmailResponse(BaseModel):
    """Response returned after a new Compose email is recorded."""

    interaction_id: UUID

    client_id: UUID | None = None

    category_id: UUID | None = None

    created_at: datetime

    attachments: list[AttachmentMetadata] = Field(default_factory=list)

    message: str = "Email sent successfully."

# mail_integration.py
#
# Schemas for the application-side email integration layer described
# in the "unified email integration" task: an outgoing send API that
# any mail provider can sit behind (Microsoft Graph included, once
# Azure AD app credentials exist — see app/ticketing/services/
# mail_provider.py), and a JSON/Graph-shaped sibling of the existing
# form-encoded POST /emails/incoming for providers that deliver a
# realistic Graph `message` resource instead of flat form fields.
#
# Nothing here replaces app/ticketing/schemas/email.py (EmailRequest/
# EmailResponse) — EmailService.receive_email, the actual Interaction-
# creation logic, is reused unchanged by both transports.

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.ticketing.schemas.payloads import OutboundEnvelope


# ---------------------------------------------------------
# Realistic Microsoft Graph `message` resource (JSON), for the
# future incoming-webhook variant.
# ---------------------------------------------------------


class GraphEmailAddress(BaseModel):
    """Mirrors Graph's `emailAddress` resource."""

    name: str | None = None
    address: EmailStr


class GraphRecipient(BaseModel):
    """Mirrors Graph's `recipient` resource (used for from/to/cc)."""

    emailAddress: GraphEmailAddress


class GraphItemBody(BaseModel):
    """Mirrors Graph's `itemBody` resource."""

    contentType: Literal["text", "html"] = "text"
    content: str = ""


class GraphInternetMessageHeader(BaseModel):
    """
    Mirrors one entry of Graph's `internetMessageHeaders` (only
    present when the message is fetched with
    `$select=internetMessageHeaders`) — this is where Graph exposes
    raw RFC 5322 headers like In-Reply-To/References that aren't
    modeled as first-class fields on the `message` resource itself.
    """

    name: str
    value: str


class IncomingMailPayload(BaseModel):
    """
    A realistic subset of Microsoft Graph's `message` resource, as it
    would arrive either fetched in response to a change-notification
    webhook, or forwarded by any other JSON-based mail provider.

    This is NOT a database entity and is NOT the same shape as
    EmailRequest (app/ticketing/schemas/email.py) — that schema
    matches the existing flat form-encoded transport. This schema
    exists to be mapped into an EmailRequest by
    map_external_email_to_interaction() (see
    app/ticketing/services/mail_mapping_service.py) before being
    handed to the unchanged EmailService.receive_email.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(
        default=None,
        description="Graph's own message id (distinct from internetMessageId).",
    )

    internetMessageId: str = Field(
        ...,
        min_length=1,
        description="RFC 5322 Message-ID — the value our EmailRequest.message_id expects.",
    )

    subject: str = Field(default="", max_length=255)

    from_: GraphRecipient = Field(..., alias="from")

    toRecipients: list[GraphRecipient] = Field(
        ...,
        min_length=1,
        description="The shared inbox address this arrived at is toRecipients[0].",
    )

    ccRecipients: list[GraphRecipient] = Field(default_factory=list)

    body: GraphItemBody

    conversationId: str | None = Field(
        default=None,
        description="Graph's own thread identifier — highest-priority thread-match signal.",
    )

    receivedDateTime: datetime | None = None

    internetMessageHeaders: list[GraphInternetMessageHeader] | None = Field(
        default=None,
        description="Only present when fetched with $select=internetMessageHeaders.",
    )


# ---------------------------------------------------------
# Outgoing send request/response
# ---------------------------------------------------------


class OutgoingEmailRequest(BaseModel):
    """
    Request body for POST /api/mail/outgoing — an email object
    authored by the frontend, to be handed to the mail provider (a
    mock today, Microsoft Graph later).

    Either `client_id` (send From the client's own shared inbox,
    same invariant the existing reply/compose flows enforce) or an
    explicit `from_email` (for a non-client, platform-level send)
    must be supplied — never both left empty.
    """

    client_id: UUID | None = Field(
        default=None,
        description="Send From this client's shared inbox address. Mutually exclusive with from_email.",
    )

    from_email: EmailStr | None = Field(
        default=None,
        description="Explicit From address, only used when client_id is omitted.",
    )
    from_name: str | None = Field(default=None, max_length=255)

    to_email: EmailStr
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)

    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1, max_length=20000)

    @model_validator(mode="after")
    def _require_a_sender(self) -> "OutgoingEmailRequest":
        if not self.client_id and not self.from_email:
            raise ValueError("Either client_id or from_email must be provided.")
        return self


class OutgoingEmailResponse(BaseModel):
    """Response returned after the (mocked) provider send call."""

    message: str
    provider_message_id: str
    status: str
    dispatched_at: datetime
    envelope: OutboundEnvelope

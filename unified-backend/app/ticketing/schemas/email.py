from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.ticketing.schemas.attachment import AttachmentMetadata


class EmailRequest(BaseModel):
    """
    Incoming email received from the communication platform
    (n8n / provider webhook — Task 1's transport layer).

    This is NOT a database entity. The EmailService converts this
    request into an Interaction.

    `to_email` is the field that matters most here: it's the shared
    inbox address the mail arrived at, and it's what resolves which
    Client (company) this email belongs to — NOT `from_email`, which
    is just the sender's address stored as contact info.
    """

    to_email: EmailStr = Field(
        ...,
        description="The shared inbox address this email arrived at — resolves the client.",
    )

    from_email: EmailStr

    from_name: str | None = Field(default=None, max_length=255)

    subject: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )

    body: str = Field(
        ...,
        min_length=1,
    )

    html_body: str | None = None

    message_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
    )

    # Mailbox arrival time reported by the provider — the SLA clock
    # start. Defaults to "now" in the service if the provider doesn't
    # supply one (e.g. the dummy-mail simulator).
    received_at: datetime | None = None

    # RFC 5322 threading headers. If in_reply_to (or anything in
    # references) matches a message_id we've already stored, this
    # email is threaded onto that conversation/ticket instead of
    # becoming a new inbox item.
    in_reply_to: str | None = Field(default=None, max_length=255)

    references: list[str] = Field(default_factory=list)

    # Microsoft Graph's own conversation identifier — unavailable
    # until Task 1 ships; accepted now (optional) so this schema
    # doesn't need to change again once it does. Highest-priority
    # thread-match signal when present (see EmailService.receive_email).
    conversation_id: str | None = Field(default=None, max_length=255)


class EmailResponse(BaseModel):
    """
    Response returned after successfully storing the email as an
    interaction.
    """

    message: str

    interaction_id: str

    client_id: str

    client_name: str

    # Set when the header match landed this email directly on an
    # existing ticket.
    ticket_id: str | None = None

    # Set whenever the header match found a thread root — whether or
    # not the conversation has since been ticketed (ticket_id above
    # tracks that separately).
    threaded_under: str | None = None

    status: str

    attachments: list[AttachmentMetadata] = Field(default_factory=list)

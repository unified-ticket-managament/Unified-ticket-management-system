from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.ticketing.schemas.attachment import AttachmentMetadata


class EmailRequest(BaseModel):
    """
    Incoming email received from the communication platform
    (n8n / provider webhook — Task 1's transport layer).

    This is NOT a database entity. The EmailService converts this
    request into an Interaction.

    Client resolution (see EmailService.receive_email) depends on
    which address this arrived at: for the one configured Microsoft
    Graph shared mailbox, every client sends into the same `to_email`,
    so the Client is resolved from `from_email` (the sender) instead;
    for any other, legacy dedicated-inbox-per-client address, `to_email`
    still resolves the Client directly, exactly as before.
    """

    to_email: EmailStr = Field(
        ...,
        description="The inbox address this email arrived at.",
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

    # Microsoft Graph's own native message id (distinct from
    # message_id above, which is the RFC 5322 Message-ID header — see
    # IncomingMailPayload.id in schemas/mail_integration.py). Not used
    # by anything yet; stored so it isn't lost for interactions
    # ingested before a future feature (native reply/replyAll/forward,
    # Sent-Items reconciliation) needs it — see this repo's own
    # architectural-gaps notes on why backfilling this later would
    # otherwise be required.
    provider_message_id: str | None = Field(default=None, max_length=255)


class EmailResponse(BaseModel):
    """
    Response returned after successfully storing the email as an
    interaction.
    """

    message: str

    interaction_id: str

    # Both None only for mail landing on the configured Graph shared
    # mailbox (GRAPH_MAILBOX_ADDRESS) with no matching Client row —
    # see EmailService.is_configured_graph_mailbox(). Every other
    # inbound transport always resolves a real Client, since any other
    # unmatched address is rejected outright ("Unknown inbox address.")
    # rather than reaching this response at all.
    client_id: str | None = None

    client_name: str | None = None

    # Set when the header match landed this email directly on an
    # existing ticket.
    ticket_id: str | None = None

    # Set whenever the header match found a thread root — whether or
    # not the conversation has since been ticketed (ticket_id above
    # tracks that separately).
    threaded_under: str | None = None

    status: str

    attachments: list[AttachmentMetadata] = Field(default_factory=list)

from pydantic import BaseModel, EmailStr, Field


class EnvelopeAttachment(BaseModel):
    """
    One file ready to ride along on an outbound send — content
    already read out of storage and base64-encoded, so the mail
    transport (graph_client.py) needs no storage/DB access of its
    own to embed it. See attachment_service.load_envelope_attachments,
    the one place this is built, for the size limit this implies
    (Graph's sendMail only accepts small inline attachments; anything
    over that limit is dropped there before it ever reaches here).
    """

    filename: str
    content_type: str
    content_base64: str


class OutboundEnvelope(BaseModel):
    """
    A fully-addressed outbound email, built by the platform before a
    reply leaves it. Stored inside the OUTBOUND interaction's
    payload (payload.envelope) — this is the seam Task 1's transport
    layer reads from to actually send the mail.

    from_email is always the client's dedicated shared inbox address
    (never an agent's personal address) — that's what keeps the
    client's next reply routable back through the platform.
    """

    from_email: EmailStr
    from_name: str | None = None

    to_email: EmailStr

    # The client's Account Manager, auto-added so they see every
    # reply in their real inbox without checking the platform, plus
    # whatever the agent themselves added via the reply/compose form.
    cc: list[EmailStr] = Field(default_factory=list)

    bcc: list[EmailStr] = Field(default_factory=list)

    subject: str

    # Newly generated for this reply, stored on the interaction so a
    # future inbound reply's In-Reply-To can be matched back to it.
    message_id: str

    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)

    body: str

    attachments: list[EnvelopeAttachment] = Field(default_factory=list)

from pydantic import BaseModel, EmailStr, Field


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
    # reply in their real inbox without checking the platform.
    cc: list[EmailStr] = Field(default_factory=list)

    subject: str

    # Newly generated for this reply, stored on the interaction so a
    # future inbound reply's In-Reply-To can be matched back to it.
    message_id: str

    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)

    body: str

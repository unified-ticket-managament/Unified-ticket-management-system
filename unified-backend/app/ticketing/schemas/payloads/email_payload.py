from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class EmailPayload(BaseModel):
    """
    Internal representation of an incoming email stored inside
    Interaction.payload.

    Every field except subject/body is optional so pre-existing rows
    (from before the client-routing rewrite — back when a "client"
    was an individual `users` row and an agent was auto-assigned)
    still deserialize without crashing; they just render with
    generic fallbacks instead of the old agent_id/agent_name fields,
    which no longer exist here.
    """

    model_config = ConfigDict(
        extra="ignore",
    )

    # The Client (company) this email belongs to, resolved from
    # to_email at receive time — NOT a `users` row.
    client_id: UUID | None = None

    client_name: str | None = Field(default=None, min_length=1)

    # The shared inbox address the email arrived at.
    to_email: EmailStr | None = None

    # Sender contact info only — no longer required to be a platform
    # user.
    from_email: EmailStr | None = None

    from_name: str | None = None

    subject: str = Field(
        ...,
        min_length=1,
    )

    body: str = Field(
        ...,
        min_length=1,
    )

    html_body: str | None = None

    in_reply_to: str | None = None

    references: list[str] = Field(default_factory=list)

    # Only ever populated on a Compose-authored root (an agent-
    # originated outbound email with no prior inbound message to
    # reply to) — an inbound email has no Cc/Bcc of its own. Optional
    # with an empty-list default so every pre-existing stored payload
    # (which never had these keys) still deserializes unchanged.
    cc: list[EmailStr] = Field(default_factory=list)

    bcc: list[EmailStr] = Field(default_factory=list)

    # Microsoft Graph's own native message id, when this email arrived
    # via the Graph transport (None for N8N-transport rows, which have
    # no such concept, and for anything ingested before this field
    # existed) — see EmailRequest.provider_message_id's own docstring
    # for what this is being kept for.
    provider_message_id: str | None = None

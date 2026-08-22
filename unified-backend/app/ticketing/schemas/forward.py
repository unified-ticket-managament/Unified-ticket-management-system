# forward.py
#
# Request/response for forwarding an existing client email
# (POST /inbox/{interaction_id}/forward) — distinct from
# ComposeEmailRequest (schemas/compose.py), which always addresses an
# external client contact from scratch rather than forwarding an
# existing interaction. The recipient is either an internal
# organization user (recipient_user_id, resolved to their own
# configured email server-side and validated against AGENT_ROLE_NAMES)
# or an arbitrary external address (recipient_email, any syntactically
# valid email — e.g. another client's mailbox) — exactly one of the
# two must be supplied. The sending mailbox is always independently
# re-validated server-side against the caller's own client
# authorization, regardless of what the frontend submitted, for
# either recipient kind.

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


class ForwardToInternalUserRequest(BaseModel):
    client_id: UUID
    recipient_user_id: UUID | None = Field(
        default=None,
        description="An existing internal user. Mutually exclusive with recipient_email.",
    )
    recipient_email: EmailStr | None = Field(
        default=None,
        description="An arbitrary external address. Mutually exclusive with recipient_user_id.",
    )
    cc: list[EmailStr] = Field(default_factory=list)
    bcc: list[EmailStr] = Field(default_factory=list)
    subject: str = Field(..., min_length=1, max_length=500)
    message: str = Field(..., min_length=1, max_length=20000)
    # Optional sanitized-on-the-backend HTML counterpart to `message`
    # (Outlook-style clipboard paste). See ReplyCreate.body_html
    # (schemas/ticket_action.py) for the same additive contract.
    body_html: str | None = None

    @model_validator(mode="after")
    def _require_exactly_one_recipient(self) -> "ForwardToInternalUserRequest":
        if bool(self.recipient_user_id) == bool(self.recipient_email):
            raise ValueError(
                "Exactly one of recipient_user_id or recipient_email must be provided."
            )
        return self


class ForwardToInternalUserResponse(BaseModel):
    interaction_id: UUID
    recipient_user_id: UUID | None
    recipient_email: str
    dispatch_status: str
    created_at: datetime

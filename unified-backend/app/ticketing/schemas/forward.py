# forward.py
#
# Request/response for forwarding an existing client email
# (POST /inbox/{interaction_id}/forward) — distinct from
# ComposeEmailRequest (schemas/compose.py), which always addresses an
# external client contact from scratch rather than forwarding an
# existing interaction. The recipient set is the union of up to three
# sources — internal organization users (recipient_user_ids, resolved
# to their own configured email server-side and validated against
# AGENT_ROLE_NAMES), arbitrary external addresses (recipient_emails,
# any syntactically valid email — e.g. another client's mailbox), and
# Distribution Lists (distribution_list_ids, resolved server-side to
# their current active members) — at least one source must be
# non-empty. The final recipient list is deduplicated case-
# insensitively by email (see recipient_merge.dedupe_emails_case_insensitive)
# and sent as ONE outbound email (one Interaction, one envelope, one
# Undo-Send window), never one send per recipient. The sending mailbox
# is always independently re-validated server-side against the
# caller's own client authorization, regardless of what the frontend
# submitted.

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


class ForwardToInternalUserRequest(BaseModel):
    client_id: UUID
    recipient_user_ids: list[UUID] = Field(default_factory=list)
    recipient_emails: list[EmailStr] = Field(default_factory=list)
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
    def _require_at_least_one_recipient_source(self) -> "ForwardToInternalUserRequest":
        if not (self.recipient_user_ids or self.recipient_emails or self.distribution_list_ids):
            raise ValueError(
                "At least one recipient (internal user, external email, or "
                "distribution list) is required."
            )
        return self


class ResolvedForwardRecipient(BaseModel):
    user_id: UUID | None
    name: str | None
    email: str


class ForwardToInternalUserResponse(BaseModel):
    interaction_id: UUID
    dispatch_status: str
    created_at: datetime
    recipients: list[ResolvedForwardRecipient]

# forward.py
#
# Request/response for forwarding an existing client email to an
# internal organization user (POST /inbox/{interaction_id}/forward) —
# distinct from ComposeEmailRequest (schemas/compose.py), which
# addresses an external client contact. The recipient here is always
# resolved to an internal user's own configured email server-side
# (never a client-submitted address), and the sending mailbox is
# always independently re-validated server-side against the caller's
# own client authorization, regardless of what the frontend submitted.

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ForwardToInternalUserRequest(BaseModel):
    client_id: UUID
    recipient_user_id: UUID
    subject: str = Field(..., min_length=1, max_length=500)
    message: str = Field(..., min_length=1, max_length=20000)


class ForwardToInternalUserResponse(BaseModel):
    interaction_id: UUID
    recipient_user_id: UUID
    recipient_email: str
    dispatch_status: str
    created_at: datetime

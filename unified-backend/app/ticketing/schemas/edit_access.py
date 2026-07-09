from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.ticketing.enums import EditAccessStatus
from app.ticketing.schemas.common import ORMBase


class EditAccessRequestCreate(BaseModel):
    """Request body for asking to work a ticket you're not assigned to."""

    reason: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Why you need to work on this ticket.",
    )


class EditAccessApproveRequest(BaseModel):
    """Request body for approving a pending edit-access request."""

    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiry for the grant. Blank means it never expires.",
    )
    review_note: str | None = Field(default=None, max_length=2000)


class EditAccessRejectRequest(BaseModel):
    """Request body for rejecting a pending edit-access request."""

    review_note: str | None = Field(default=None, max_length=2000)


class EditAccessRequestResponse(ORMBase):
    request_id: UUID
    ticket_id: UUID
    requested_by: UUID
    requested_by_name: str | None = None
    reason: str
    status: EditAccessStatus
    reviewed_by: UUID | None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None
    review_note: str | None
    expires_at: datetime | None
    created_at: datetime

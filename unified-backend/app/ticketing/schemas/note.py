from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.ticketing.schemas.common import ORMBase


class InternalNoteCreate(BaseModel):
    """
    Request body for adding an internal note
    to an existing ticket.
    """

    subject: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Short summary shown on the ticket timeline.",
    )

    note: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Internal note visible only to agents.",
    )

    recipient_user_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "Platform users this note is addressed to. Any active "
            "user (any role) is eligible — recipient selection is not "
            "restricted by reporting hierarchy, role, department, "
            "team, or category. Optional for backward compatibility: "
            "an empty list falls back to the pre-existing "
            "stakeholder-notification behavior."
        ),
    )


class InternalNoteResponse(ORMBase):
    """
    Response returned after successfully
    creating an internal note.
    """

    interaction_id: UUID
    ticket_id: UUID
    message: str
    created_at: datetime
    recipient_user_ids: list[UUID] = Field(default_factory=list)
    recipient_names: list[str] = Field(default_factory=list)


class InternalNoteRecipientCandidate(BaseModel):
    """
    One eligible Internal Note "To" option — any active platform
    user, company-wide, regardless of role/reporting-hierarchy/
    department/team/category. See
    InteractionService.list_internal_note_recipients and
    UserRepository.list_all_active for why this is its own purpose-
    built listing rather than RBAC's own (hierarchy-scoped) user list.
    """

    user_id: UUID
    name: str
    email: str
    role_name: str

    model_config = {"from_attributes": True}


class InternalNoteRecipientsResponse(BaseModel):
    recipients: list[InternalNoteRecipientCandidate]
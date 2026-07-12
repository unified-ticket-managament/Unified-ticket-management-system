from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

#client.py
class ClientCreate(BaseModel):
    """
    Request body for onboarding a new client company.
    """

    name: str = Field(..., min_length=1, max_length=255)

    inbox_email: EmailStr = Field(
        ...,
        description="Dedicated shared inbox address given to this client at onboarding.",
    )

    account_manager_id: UUID = Field(
        ...,
        description="The Account Manager who owns this client relationship.",
    )


class ClientResponse(BaseModel):
    """
    Response returned for a client company.
    """

    client_id: UUID
    name: str
    inbox_email: str
    account_manager_id: UUID
    is_active: bool
    created_at: datetime

    # Resolved from the `users` table by ClientService — not
    # persisted on the client row itself.
    account_manager_name: str | None = None

    # False when account_manager_id points at a user who is no longer
    # an active Account Manager (their role changed, or they were
    # deactivated, after this client was onboarded — nothing
    # revalidates that automatically). Always True right after
    # creation, since ClientService.create validates it up front.
    account_manager_active: bool = True


class ClientContactResponse(BaseModel):
    """
    One personal email address this client company has contacted our
    shared inbox from, most-recently-used first — populates the "To"
    picker on a reply composer so an agent can address a reply to any
    contact who has actually emailed in, not just whoever sent the
    specific thread being replied to.
    """

    email: str
    name: str | None = None

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

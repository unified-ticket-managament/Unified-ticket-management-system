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
    # The client's official distribution/intake address — None when
    # it has no configured distribution email (see Client's own
    # docstring; never inferred from a contact/employee address).
    inbox_email: str | None
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


class ClientDetailsResponse(ClientResponse):
    """
    Response for GET /clients/{client_id}/details — the Roles page's
    Client-tab expand action, gated by client:view (see
    access_control.ensure_can_view_client_details). Adds this client's
    configured contact emails (the same rows
    ClientService.list_contacts(..., configured_only=True) already
    returns for the pre-existing, ungated GET /clients/{id}/contacts
    route) on top of every field ClientResponse already carries, so
    the Roles page needs exactly one gated call instead of reading
    organization-email/account-manager fields off the already-fetched,
    ungated listClients() array plus a second contacts call.
    """

    contacts: list[ClientContactResponse] = []

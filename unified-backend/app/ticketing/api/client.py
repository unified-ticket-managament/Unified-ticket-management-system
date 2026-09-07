from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent, get_current_user
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.client import (
    ClientContactResponse,
    ClientCreate,
    ClientDetailsResponse,
    ClientResponse,
)
from app.ticketing.services.access_control import (
    ACCOUNT_MANAGER_ROLE_NAME,
    ensure_can_view_client_details,
    ensure_has_permission,
)
from app.ticketing.services.client_service import ClientService
from app.rbac.repositories.category_repository import CategoryRepository

router = APIRouter(
    prefix="/clients",
    tags=["Clients"],
)


@router.post(
    "",
    response_model=ClientResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_client(
    request: ClientCreate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Onboards a new client company: a name, its dedicated shared
    inbox address, and the Account Manager who owns it.
    """

    # Reuses client:view (the same permission GET /clients/{id}/details
    # already gates via ensure_can_view_client_details) rather than a
    # new client:create — no pre-existing object to scope ownership
    # against on creation, so a plain permission check is the whole
    # gate. See RBAC Enforcement Audit, Phase 2C.
    ensure_has_permission(current_user, "client:view")

    service = ClientService(
        client_repository=ClientRepository(db),
        user_repository=UserRepository(db),
        category_repository=CategoryRepository(db),
    )

    return await service.create(request, current_user=current_user)


@router.get(
    "",
    response_model=list[ClientResponse],
)
async def list_clients(
    mine: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Lists onboarded clients — used to populate the shared-inbox picker
    on the mail simulator, the Roles page's Client-tab roster, the
    Rules engine's client picker, and the Client filter dropdowns
    across Tickets/Interactions/Audit Log/Mail/Dashboard/Reports.

    `?mine=true` narrows the list to the clients owned by the calling
    Account Manager (Client.account_manager_id == their user_id) —
    a no-op for every other role. Omitting it (every caller that
    predates this flag) is byte-identical to the old unconditional
    behavior, so the Roles page roster and the Rules engine picker
    deliberately don't pass it and keep seeing every client.
    """

    account_manager_id = (
        current_user.user_id
        if mine and current_user.role.name == ACCOUNT_MANAGER_ROLE_NAME
        else None
    )

    service = ClientService(
        client_repository=ClientRepository(db),
        user_repository=UserRepository(db),
    )

    return await service.list_all(account_manager_id=account_manager_id)


@router.get(
    "/{client_id}/details",
    response_model=ClientDetailsResponse,
)
async def get_client_details(
    client_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregated client detail view (organization email, account manager
    name/active, configured contact emails) for the Roles page's
    Client-tab expand action — gated by client:view, unlike GET
    /clients (list) and GET /clients/{id}/contacts, which stay ungated
    on purpose (see ensure_can_view_client_details' own docstring for
    the full list of shared callers that would otherwise break).
    """

    ensure_can_view_client_details(current_user)

    service = ClientService(
        client_repository=ClientRepository(db),
        user_repository=UserRepository(db),
        interaction_repository=InteractionRepository(db),
    )

    return await service.get_details(client_id)


@router.get(
    "/{client_id}/contacts",
    response_model=list[ClientContactResponse],
)
async def list_client_contacts(
    client_id: UUID,
    configured_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Every distinct personal email address this client company has
    contacted our shared inbox from, most-recently-used first — used
    by the reply composer's "To" dropdown so an agent isn't limited
    to whichever contact happened to send the thread being replied to.

    `?configured_only=true` returns just the curated `client_contacts`
    rows instead (no interaction-derived merge) — see
    ClientService.list_contacts' own docstring for why the Edit
    Client form needs this narrower variant rather than the default
    merged list.
    """

    service = ClientService(
        client_repository=ClientRepository(db),
        user_repository=UserRepository(db),
        interaction_repository=InteractionRepository(db),
    )

    return await service.list_contacts(client_id, configured_only=configured_only)

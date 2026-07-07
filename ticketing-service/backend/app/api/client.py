from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent, get_current_user
from app.repositories.client_repository import ClientRepository
from app.repositories.user_repository import UserRepository
from app.schemas.client import ClientCreate, ClientResponse
from app.services.client_service import ClientService

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

    service = ClientService(
        client_repository=ClientRepository(db),
        user_repository=UserRepository(db),
    )

    return await service.create(request, current_user=current_user)


@router.get(
    "",
    response_model=list[ClientResponse],
)
async def list_clients(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Lists every onboarded client — used to populate the shared-inbox
    picker on the mail simulator and the client filter on the inbox.
    """

    service = ClientService(
        client_repository=ClientRepository(db),
        user_repository=UserRepository(db),
    )

    return await service.list_all()

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.repositories.mail_folder_repository import MailFolderRepository
from app.schemas.mail_folder import MailFolderCreate, MailFolderResponse
from app.services.mail_folder_service import MailFolderService

router = APIRouter(
    prefix="/folders",
    tags=["Mail Folders"],
)


@router.get(
    "",
    response_model=list[MailFolderResponse],
)
async def list_folders(
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Every custom mail folder — global/shared across the org, not
    scoped per-user.
    """

    service = MailFolderService(MailFolderRepository(db))
    return await service.list_all()


@router.post(
    "",
    response_model=MailFolderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder(
    request: MailFolderCreate,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    service = MailFolderService(MailFolderRepository(db))
    return await service.create(request, current_user=current_user)


@router.delete(
    "/{folder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_folder(
    folder_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    service = MailFolderService(MailFolderRepository(db))
    await service.delete(folder_id)

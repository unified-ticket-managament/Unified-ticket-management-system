from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.repositories.mail_folder_repository import MailFolderRepository
from app.schemas.mail_folder import MailFolderCreate, MailFolderResponse


class MailFolderService:
    """
    CRUD for custom mail folders (Billing/Claims/General/...) —
    global/shared across the org, not per-user. No audit logging here
    (unlike interaction-level actions): creating/deleting a folder is
    an org-config action, not a client-communication event.
    """

    def __init__(self, mail_folder_repository: MailFolderRepository):
        self.mail_folder_repository = mail_folder_repository

    async def list_all(self) -> list[MailFolderResponse]:
        folders = await self.mail_folder_repository.list_all()
        return [MailFolderResponse.model_validate(folder) for folder in folders]

    async def create(
        self,
        request: MailFolderCreate,
        current_user: User,
    ) -> MailFolderResponse:
        existing = await self.mail_folder_repository.get_by_name(request.name)

        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A folder with this name already exists.",
            )

        folder = await self.mail_folder_repository.create(
            request.name, current_user.user_id
        )

        return MailFolderResponse.model_validate(folder)

    async def delete(self, folder_id: UUID) -> None:
        folder = await self.mail_folder_repository.get_by_id(folder_id)

        if folder is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Folder not found.",
            )

        await self.mail_folder_repository.delete(folder)

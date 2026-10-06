from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.mail_folder import MailFolder


class MailFolderRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[MailFolder]:
        result = await self.db.execute(
            select(MailFolder).order_by(MailFolder.name.asc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, folder_id: UUID) -> MailFolder | None:
        result = await self.db.execute(
            select(MailFolder).where(MailFolder.folder_id == folder_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> MailFolder | None:
        result = await self.db.execute(
            select(MailFolder).where(MailFolder.name == name)
        )
        return result.scalar_one_or_none()

    async def list_children(self, parent_folder_id: UUID) -> list[MailFolder]:
        result = await self.db.execute(
            select(MailFolder).where(MailFolder.parent_folder_id == parent_folder_id)
        )
        return list(result.scalars().all())

    async def set_parent(self, folder: MailFolder, parent_folder_id: UUID | None) -> None:
        folder.parent_folder_id = parent_folder_id
        await self.db.flush()

    async def set_name(self, folder: MailFolder, name: str) -> None:
        folder.name = name
        await self.db.flush()

    async def create(
        self,
        name: str,
        created_by: UUID | None,
        *,
        is_rule_created: bool = False,
        parent_folder_id: UUID | None = None,
    ) -> MailFolder:
        folder = MailFolder(
            name=name,
            created_by=created_by,
            is_rule_created=is_rule_created,
            parent_folder_id=parent_folder_id,
        )
        self.db.add(folder)
        await self.db.flush()
        await self.db.refresh(folder)
        return folder

    async def delete(self, folder: MailFolder) -> None:
        await self.db.delete(folder)
        await self.db.flush()

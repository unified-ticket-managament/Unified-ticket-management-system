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

    async def create(self, name: str, created_by: UUID | None) -> MailFolder:
        folder = MailFolder(name=name, created_by=created_by)
        self.db.add(folder)
        await self.db.flush()
        await self.db.refresh(folder)
        return folder

    async def delete(self, folder: MailFolder) -> None:
        await self.db.delete(folder)
        await self.db.flush()

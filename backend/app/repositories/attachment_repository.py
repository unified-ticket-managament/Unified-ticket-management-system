# attachment_repository.py
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.schemas.attachment import AttachmentCreate


class AttachmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: AttachmentCreate) -> Attachment:
        attachment = Attachment(**data.model_dump())
        self.db.add(attachment)
        await self.db.flush()
        await self.db.refresh(attachment)
        return attachment

    async def get_by_id(self, attachment_id: UUID) -> Attachment | None:
        result = await self.db.execute(
            select(Attachment).where(
                Attachment.attachment_id == attachment_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_interaction_id(
        self,
        interaction_id: UUID,
    ) -> list[Attachment]:
        result = await self.db.execute(
            select(Attachment)
            .where(Attachment.interaction_id == interaction_id)
            .order_by(Attachment.uploaded_at.asc())
        )
        return list(result.scalars().all())

    async def delete(self, attachment: Attachment) -> None:
        await self.db.delete(attachment)
        await self.db.flush()
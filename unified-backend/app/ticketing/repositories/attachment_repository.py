# attachment_repository.py
from collections import defaultdict
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.attachment import Attachment
from app.ticketing.schemas.attachment import AttachmentCreate

#attachment_repository.py
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

    async def list_by_interaction_ids(
        self,
        interaction_ids: list[UUID],
    ) -> dict[UUID, list[Attachment]]:
        """
        Bulk fetch, grouped by interaction_id — avoids one query
        per interaction when building a ticket timeline or an
        inbox listing.
        """
        if not interaction_ids:
            return {}

        result = await self.db.execute(
            select(Attachment)
            .where(Attachment.interaction_id.in_(interaction_ids))
            .order_by(Attachment.uploaded_at.asc())
        )

        grouped: dict[UUID, list[Attachment]] = defaultdict(list)
        for attachment in result.scalars().all():
            grouped[attachment.interaction_id].append(attachment)
        return grouped

    async def has_attachments_for_interactions(
        self,
        interaction_ids: list[UUID],
    ) -> set[UUID]:
        if not interaction_ids:
            return set()

        result = await self.db.execute(
            select(Attachment.interaction_id)
            .where(Attachment.interaction_id.in_(interaction_ids))
            .distinct()
        )
        return set(result.scalars().all())

    async def delete(self, attachment: Attachment) -> None:
        await self.db.delete(attachment)
        await self.db.flush()

    async def reassign_interaction(
        self,
        old_interaction_id: UUID,
        new_interaction_id: UUID,
    ) -> None:
        """
        Re-points every attachment from one interaction to another —
        used when a draft is sent: the draft's own interaction row is
        deleted, but files already uploaded against it must keep
        pointing at a live row (the newly-created sent reply) rather
        than being orphaned.
        """

        await self.db.execute(
            update(Attachment)
            .where(Attachment.interaction_id == old_interaction_id)
            .values(interaction_id=new_interaction_id)
        )
        await self.db.flush()
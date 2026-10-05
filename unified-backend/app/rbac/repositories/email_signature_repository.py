from datetime import datetime
from uuid import UUID

from sqlalchemy import Text, cast, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared_models.models import User

from app.rbac.models.email_signature import EmailSignature, EmailSignatureImage
from app.ticketing.models.attachment import Attachment
from app.ticketing.models.interaction import Interaction

from .base import BaseRepository


class EmailSignatureRepository(BaseRepository):
    """
    Persistence for EmailSignature/EmailSignatureImage. Every read and
    write is scoped by `user_id` — callers always pass the request's
    effective user (see EmailSignatureService), so a signature id from
    another account simply isn't found.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def lock_user(self, user_id: UUID) -> None:
        """
        Serializes signature mutations per user (SELECT ... FOR UPDATE
        on the owning users row) for the rest of the request's
        transaction, so "first signature becomes default" and "deleting
        the default promotes another" can't race a concurrent create/
        delete/set-default into zero or two defaults. The partial unique
        index on is_default is the final backstop either way.
        """

        await self.db.execute(
            select(User.user_id).where(User.user_id == user_id).with_for_update()
        )

    # ---------------- signatures ----------------

    async def list_for_user(self, user_id: UUID) -> list[EmailSignature]:
        result = await self.db.execute(
            select(EmailSignature)
            .where(EmailSignature.user_id == user_id)
            .order_by(EmailSignature.created_at, EmailSignature.signature_id)
        )
        return list(result.scalars().all())

    async def get_for_user(self, user_id: UUID, signature_id: UUID) -> EmailSignature | None:
        result = await self.db.execute(
            select(EmailSignature).where(
                EmailSignature.user_id == user_id,
                EmailSignature.signature_id == signature_id,
            )
        )
        return result.scalar_one_or_none()

    async def add(self, signature: EmailSignature) -> EmailSignature:
        self.db.add(signature)
        await self.db.flush()
        return signature

    async def save(self, signature: EmailSignature) -> EmailSignature:
        await self.db.flush()
        return signature

    async def delete(self, signature: EmailSignature) -> None:
        await self.db.delete(signature)
        await self.db.flush()

    async def clear_default(self, user_id: UUID) -> None:
        # Its own statement, flushed before any row is set true — a
        # non-deferrable unique index is checked per row, so flipping
        # both in one UPDATE could transiently see two defaults.
        await self.db.execute(
            update(EmailSignature)
            .where(EmailSignature.user_id == user_id, EmailSignature.is_default.is_(True))
            .values(is_default=False)
            .execution_options(synchronize_session="fetch")
        )
        await self.db.flush()

    # ---------------- images ----------------

    async def add_image(self, image: EmailSignatureImage) -> EmailSignatureImage:
        self.db.add(image)
        await self.db.flush()
        return image

    async def list_images_by_ids(
        self, user_id: UUID, image_ids: list[UUID]
    ) -> list[EmailSignatureImage]:
        if not image_ids:
            return []
        result = await self.db.execute(
            select(EmailSignatureImage).where(
                EmailSignatureImage.user_id == user_id,
                EmailSignatureImage.image_id.in_(image_ids),
            )
        )
        return list(result.scalars().all())

    async def list_images_created_before(
        self, user_id: UUID, cutoff: datetime
    ) -> list[EmailSignatureImage]:
        result = await self.db.execute(
            select(EmailSignatureImage).where(
                EmailSignatureImage.user_id == user_id,
                EmailSignatureImage.created_at < cutoff,
            )
        )
        return list(result.scalars().all())

    async def is_storage_key_used_by_attachment(self, storage_key: str) -> bool:
        result = await self.db.execute(
            select(exists().where(Attachment.storage_key == storage_key))
        )
        return bool(result.scalar())

    async def is_content_id_in_user_drafts(self, user_id: UUID, content_id: str) -> bool:
        """
        Whether any of this user's still-unsent drafts references
        `content_id` — such an image has no Attachment row yet (those
        are only created at send time), but deleting it would leave the
        draft with a broken image once it's finally sent. Matches on
        the payload's text form so every draft shape (Compose, pre-
        ticket Reply, Ticket Reply) is covered regardless of which key
        it stores its HTML under.
        """

        result = await self.db.execute(
            select(
                exists().where(
                    Interaction.performed_by == user_id,
                    Interaction.payload["dispatch_status"].astext == "DRAFT",
                    cast(Interaction.payload, Text).contains(content_id),
                )
            )
        )
        return bool(result.scalar())

    async def delete_image(self, image: EmailSignatureImage) -> None:
        await self.db.delete(image)
        await self.db.flush()

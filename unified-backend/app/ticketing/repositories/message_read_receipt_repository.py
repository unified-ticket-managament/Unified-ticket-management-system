from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.message_read_receipt import MessageReadReceipt


class MessageReadReceiptRepository:
    """
    Persisted "has this user opened this thread" tracking — the
    backend counterpart to what used to be a purely client-side,
    session-only concept. See MessageReadReceipt's own docstring.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def mark_read(self, user_id: UUID, interaction_id: UUID) -> None:
        """
        Idempotent — a thread opened many times by the same user only
        ever keeps the first `read_at`. Safe to call on every thread
        open with no "already read, skip" check needed by the caller.
        """

        stmt = (
            pg_insert(MessageReadReceipt)
            .values(user_id=user_id, interaction_id=interaction_id)
            .on_conflict_do_nothing(
                index_elements=["user_id", "interaction_id"]
            )
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def get_read_interaction_ids(
        self,
        user_id: UUID,
        interaction_ids: list[UUID],
    ) -> set[UUID]:
        """
        Batched membership check for a page of inbox rows — one query
        for the whole page, not one per row.
        """

        if not interaction_ids:
            return set()

        result = await self.db.execute(
            select(MessageReadReceipt.interaction_id).where(
                MessageReadReceipt.user_id == user_id,
                MessageReadReceipt.interaction_id.in_(interaction_ids),
            )
        )
        return set(result.scalars().all())

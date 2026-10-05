from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.message_mark import MessageMark


class MessageMarkRepository:
    """Per-user Flag / Pin on a thread root. See MessageMark."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _set(self, user_id: UUID, interaction_id: UUID, column: str, on: bool) -> None:
        value = datetime.now(timezone.utc) if on else None
        stmt = (
            pg_insert(MessageMark)
            .values(user_id=user_id, interaction_id=interaction_id, **{column: value})
            .on_conflict_do_update(
                index_elements=["user_id", "interaction_id"],
                set_={column: value},
            )
        )
        await self.db.execute(stmt)
        # A row with neither mark on carries no information — drop it.
        await self.db.execute(
            delete(MessageMark).where(
                MessageMark.user_id == user_id,
                MessageMark.interaction_id == interaction_id,
                MessageMark.flagged_at.is_(None),
                MessageMark.pinned_at.is_(None),
            )
        )
        await self.db.flush()

    async def set_flag(self, user_id: UUID, interaction_id: UUID, flagged: bool) -> None:
        await self._set(user_id, interaction_id, "flagged_at", flagged)

    async def set_pin(self, user_id: UUID, interaction_id: UUID, pinned: bool) -> None:
        await self._set(user_id, interaction_id, "pinned_at", pinned)

    async def get_marks(
        self, user_id: UUID, interaction_ids: list[UUID]
    ) -> dict[UUID, tuple[bool, bool]]:
        """Batched (is_flagged, is_pinned) for a page of rows — one query."""

        if not interaction_ids:
            return {}
        result = await self.db.execute(
            select(
                MessageMark.interaction_id,
                MessageMark.flagged_at,
                MessageMark.pinned_at,
            ).where(
                MessageMark.user_id == user_id,
                MessageMark.interaction_id.in_(interaction_ids),
            )
        )
        return {
            row.interaction_id: (row.flagged_at is not None, row.pinned_at is not None)
            for row in result.all()
        }

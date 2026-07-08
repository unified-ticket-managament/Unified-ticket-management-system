from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket_relation import TicketRelation


class TicketRelationRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_related_ticket_ids(self, ticket_id: UUID) -> list[UUID]:
        """
        Every ticket related to this one — a single lookup regardless
        of which side of the pair `ticket_id` was originally linked
        from, since `create` writes both directions.
        """

        result = await self.db.execute(
            select(TicketRelation.related_ticket_id).where(
                TicketRelation.ticket_id == ticket_id
            )
        )

        return list(result.scalars().all())

    async def exists(self, ticket_id: UUID, related_ticket_id: UUID) -> bool:
        result = await self.db.execute(
            select(TicketRelation.ticket_id).where(
                TicketRelation.ticket_id == ticket_id,
                TicketRelation.related_ticket_id == related_ticket_id,
            )
        )

        return result.scalar_one_or_none() is not None

    async def create(self, ticket_id: UUID, related_ticket_id: UUID) -> None:
        """Writes both directions of the symmetric link in one go."""

        self.db.add(TicketRelation(ticket_id=ticket_id, related_ticket_id=related_ticket_id))
        self.db.add(TicketRelation(ticket_id=related_ticket_id, related_ticket_id=ticket_id))

        await self.db.flush()

    async def delete(self, ticket_id: UUID, related_ticket_id: UUID) -> int:
        """Removes both directions. Returns the number of rows actually deleted."""

        result = await self.db.execute(
            delete(TicketRelation).where(
                or_(
                    and_(
                        TicketRelation.ticket_id == ticket_id,
                        TicketRelation.related_ticket_id == related_ticket_id,
                    ),
                    and_(
                        TicketRelation.ticket_id == related_ticket_id,
                        TicketRelation.related_ticket_id == ticket_id,
                    ),
                )
            )
        )

        await self.db.flush()

        return result.rowcount

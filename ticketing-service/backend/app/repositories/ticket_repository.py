# ticket_repository.py
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import TicketStatus
from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate, TicketUpdate

CLOSED_STATUSES = (TicketStatus.RESOLVED, TicketStatus.CLOSED)

#ticket_repository.py
class TicketRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: TicketCreate) -> Ticket:
        ticket = Ticket(**data.model_dump())
        self.db.add(ticket)
        await self.db.flush()
        await self.db.refresh(ticket)
        return ticket

    async def get_by_id(self, ticket_id: UUID) -> Ticket | None:
        result = await self.db.execute(
            select(Ticket).where(Ticket.ticket_id == ticket_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self, agent_id: UUID | None = None) -> list[Ticket]:
        query = select(Ticket).order_by(Ticket.created_at.desc())

        if agent_id is not None:
            # Unassigned tickets stay visible to everyone so they
            # don't become permanently invisible to any agent.
            query = query.where(
                or_(Ticket.agent_id == agent_id, Ticket.agent_id.is_(None))
            )

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update(self, ticket: Ticket, data: TicketUpdate) -> Ticket:
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(ticket, field, value)

        await self.db.flush()
        await self.db.refresh(ticket)
        return ticket

    async def delete(self, ticket: Ticket) -> None:
        await self.db.delete(ticket)
        await self.db.flush()

    async def count_open_tickets_by_agent(
        self,
        agent_ids: list[UUID],
    ) -> dict[UUID, int]:
        """
        Number of not-yet-closed tickets currently held by
        each of the given agents. Used as the workload signal
        for interim agent assignment.
        """

        if not agent_ids:
            return {}

        result = await self.db.execute(
            select(Ticket.agent_id, func.count(Ticket.ticket_id))
            .where(
                Ticket.agent_id.in_(agent_ids),
                Ticket.current_status.notin_(CLOSED_STATUSES),
            )
            .group_by(Ticket.agent_id)
        )
        return dict(result.all())
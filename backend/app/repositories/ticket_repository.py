# ticket_repository.py
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate, TicketUpdate

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

    async def list_all(self) -> list[Ticket]:
        result = await self.db.execute(
            select(Ticket).order_by(Ticket.created_at.desc())
        )
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
# ticket_repository.py
from uuid import UUID

from sqlalchemy import or_, select, update
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

    async def list_all(
        self,
        agent_id: UUID | None = None,
        client_company_ids: list[UUID] | None = None,
    ) -> list[Ticket]:
        query = select(Ticket).order_by(Ticket.created_at.desc())

        if agent_id is not None:
            # Unassigned tickets stay visible to everyone so they
            # don't become permanently invisible to any agent.
            query = query.where(
                or_(Ticket.agent_id == agent_id, Ticket.agent_id.is_(None))
            )

        if client_company_ids is not None:
            # Account Manager scoping — restrict to tickets belonging
            # to clients they own. An empty list is a deliberate "owns
            # no clients, sees nothing" rather than "unrestricted".
            query = query.where(Ticket.client_company_id.in_(client_company_ids))

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

    async def claim(self, ticket: Ticket, agent_id: UUID) -> Ticket | None:
        """
        Atomically assigns an unclaimed OPEN ticket to `agent_id` and
        moves it to IN_PROGRESS.

        Guarded by a conditional UPDATE (`agent_id IS NULL AND
        current_status = OPEN`) rather than a plain ORM attribute
        set — two agents clicking Claim on the same ticket at the
        same moment both read agent_id=None, so only a WHERE-gated
        UPDATE can guarantee just one of them wins. Returns None
        (instead of overwriting) when the guard fails, so the caller
        can turn that into a 409 rather than silently stealing the
        ticket from whoever claimed it first.
        """

        result = await self.db.execute(
            update(Ticket)
            .where(
                Ticket.ticket_id == ticket.ticket_id,
                Ticket.agent_id.is_(None),
                Ticket.current_status == TicketStatus.OPEN,
            )
            .values(agent_id=agent_id, current_status=TicketStatus.IN_PROGRESS)
        )

        if result.rowcount == 0:
            return None

        await self.db.flush()
        await self.db.refresh(ticket)

        return ticket
# interaction_repository.py
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interaction import Interaction
from app.schemas.interaction import InteractionCreate, InteractionUpdate


class InteractionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: InteractionCreate) -> Interaction:
        interaction = Interaction(**data.model_dump())
        self.db.add(interaction)
        await self.db.flush()
        await self.db.refresh(interaction)
        return interaction

    async def get_by_id(self, interaction_id: UUID) -> Interaction | None:
        result = await self.db.execute(
            select(Interaction).where(
                Interaction.interaction_id == interaction_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_ticket_id(self, ticket_id: UUID) -> list[Interaction]:
        result = await self.db.execute(
            select(Interaction)
            .where(Interaction.ticket_id == ticket_id)
            .order_by(Interaction.created_at.asc())
        )
        return list(result.scalars().all())

    async def update(
        self,
        interaction: Interaction,
        data: InteractionUpdate,
    ) -> Interaction:
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(interaction, field, value)

        await self.db.flush()
        await self.db.refresh(interaction)
        return interaction
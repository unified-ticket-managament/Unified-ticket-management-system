from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import InteractionStatus
from app.models.interaction import Interaction
from app.schemas.interaction import (
    InteractionCreate,
    InteractionUpdate,
)


class InteractionRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        data: InteractionCreate,
    ) -> Interaction:

        interaction = Interaction(**data.model_dump())

        self.db.add(interaction)

        await self.db.flush()

        await self.db.refresh(interaction)

        return interaction

    async def get_by_id(
        self,
        interaction_id: UUID,
    ) -> Interaction | None:

        result = await self.db.execute(

            select(Interaction).where(
                Interaction.interaction_id == interaction_id
            )

        )

        return result.scalar_one_or_none()

    async def list_by_ticket_id(
        self,
        ticket_id: UUID,
    ) -> list[Interaction]:

        result = await self.db.execute(

            select(Interaction)
            .where(
                Interaction.ticket_id == ticket_id
            )
            .order_by(
                Interaction.created_at.asc()
            )

        )

        return list(result.scalars().all())

    async def list_pending_inbox(
        self,
        agent_name: str,
    ) -> list[Interaction]:

        result = await self.db.execute(

            select(Interaction)
            .where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
                Interaction.payload["agent_name"].astext == agent_name,
                # A soft-deleted inbox item should actually leave
                # the actionable queue, unlike a hidden interaction
                # on a ticket timeline (which stays visible, dimmed,
                # for audit purposes).
                Interaction.is_visible.is_(True),
            )
            .order_by(
                Interaction.created_at.asc()
            )

        )

        return list(result.scalars().all())

    async def count_pending_by_agent(
        self,
        agent_ids: list[UUID],
    ) -> dict[UUID, int]:
        """
        Number of not-yet-ticketed pending emails currently
        sitting in each agent's inbox. Combined with open-ticket
        counts, this is the workload signal for interim agent
        assignment — without it, a burst of new emails would all
        land on the same agent until the first ticket is created.
        """

        if not agent_ids:
            return {}

        agent_id_strings = [str(agent_id) for agent_id in agent_ids]

        agent_id_column = Interaction.payload["agent_id"].astext

        result = await self.db.execute(
            select(agent_id_column, func.count(Interaction.interaction_id))
            .where(
                Interaction.status == InteractionStatus.PENDING,
                agent_id_column.in_(agent_id_strings),
            )
            .group_by(agent_id_column)
        )

        return {UUID(agent_id_str): count for agent_id_str, count in result.all()}

    async def update(
        self,
        interaction: Interaction,
        data: InteractionUpdate,
    ) -> Interaction:

        update_data = data.model_dump(
            exclude_unset=True
        )

        for field, value in update_data.items():
            setattr(interaction, field, value)

        await self.db.flush()

        await self.db.refresh(interaction)

        return interaction

    async def assign_to_ticket(
        self,
        interaction: Interaction,
        ticket_id: UUID,
    ) -> Interaction:
        """
        Assign an inbox interaction to a ticket.

        Used when an agent creates a new ticket
        or attaches the email to an existing ticket.
        """

        interaction.ticket_id = ticket_id

        interaction.status = InteractionStatus.ASSIGNED

        await self.db.flush()

        await self.db.refresh(interaction)

        return interaction

    async def exists_by_message_id(
        self,
        message_id: str,
    ) -> bool:
        """
        Check whether an interaction with the given
        email message_id already exists.
        """

        result = await self.db.execute(
            select(Interaction.interaction_id).where(
                Interaction.message_id == message_id
            )
        )

        return result.scalar_one_or_none() is not None

    async def hide(
        self,
        interaction: Interaction,
        removed_by: UUID | None,
    ) -> Interaction:
        """
        Soft-deletes an interaction.

        The interaction row is never removed from the
        database; it is simply marked as not visible,
        preserving the full ticket timeline and audit trail.
        """

        interaction.is_visible = False

        interaction.removed_by = removed_by

        interaction.removed_at = datetime.now(timezone.utc)

        await self.db.flush()

        await self.db.refresh(interaction)

        return interaction
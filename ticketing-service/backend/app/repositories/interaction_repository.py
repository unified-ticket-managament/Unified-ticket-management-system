from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import InteractionStatus
from app.models.client import Client
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

    async def list_inbox(
        self,
        account_manager_id: UUID | None = None,
        client_id: UUID | None = None,
        view: str = "pending",
    ) -> list[Interaction]:
        """
        The Account Manager inbox query — always over thread ROOTS
        (parent_interaction_id IS NULL, interaction_type == "EMAIL");
        replies are fetched separately via `list_thread` once a root
        is opened.

        - `account_manager_id` set: only mail belonging to clients
          that AM owns (a join against `clients`). None means "every
          client" — the Manager/Super Admin escape hatch for when an
          AM is on leave, or the "All Inboxes" overview.
        - `client_id` set: further narrows to one client (the
          per-client filter on the inbox UI).
        - `view`:
          - "pending": not yet replied to or ticketed — the triage queue.
          - "replied": answered directly, never became a ticket.
          - "ticketed": promoted to (or attached onto) a ticket.
          - "all": every root email regardless of state — the "All
            Inboxes" overview, normally paired with no account_manager
            scoping.
        """

        query = select(Interaction)

        if account_manager_id is not None or client_id is not None:
            query = query.join(Client, Client.client_id == Interaction.client_id)

        if account_manager_id is not None:
            query = query.where(Client.account_manager_id == account_manager_id)

        if client_id is not None:
            query = query.where(Interaction.client_id == client_id)

        query = query.where(
            Interaction.is_visible.is_(True),
            Interaction.interaction_type == "EMAIL",
            Interaction.parent_interaction_id.is_(None),
        )

        if view == "pending":
            query = query.where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
            )
        elif view == "replied":
            query = query.where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.ASSIGNED,
            )
        elif view == "ticketed":
            query = query.where(Interaction.ticket_id.isnot(None))
        # view == "all": no further filter — every root email.

        query = query.order_by(Interaction.received_at.desc())

        result = await self.db.execute(query)

        return list(result.scalars().all())

    async def list_thread(
        self,
        root_interaction_id: UUID,
    ) -> list[Interaction]:
        """
        Every reply/follow-up filed under a thread root, oldest
        first — the conversation shown under an inbox email.
        """

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.parent_interaction_id == root_interaction_id,
                Interaction.is_visible.is_(True),
            )
            .order_by(Interaction.created_at.asc())
        )

        return list(result.scalars().all())

    async def get_by_message_ids(
        self,
        message_ids: list[str],
    ) -> list[Interaction]:
        """
        Looks up interactions by their message_id — the thread-match
        step: an inbound email's In-Reply-To/References are checked
        against message_ids we've already stored (ours or the
        client's) to decide whether it's a new conversation or a
        continuation of one.
        """

        if not message_ids:
            return []

        result = await self.db.execute(
            select(Interaction).where(Interaction.message_id.in_(message_ids))
        )

        return list(result.scalars().all())

    async def assign_thread_to_ticket(
        self,
        root_interaction_id: UUID,
        ticket_id: UUID,
    ) -> None:
        """
        Moves an entire inbox thread (its root plus every reply
        filed under it) onto a ticket in one go — used when a
        pending email (or a whole conversation under it) is
        promoted to a ticket, so replies already exchanged before
        the ticket existed still show up on its timeline.
        """

        root = await self.get_by_id(root_interaction_id)
        if root is not None and root.ticket_id is None:
            root.ticket_id = ticket_id
            root.status = InteractionStatus.ASSIGNED

        thread = await self.list_thread(root_interaction_id)
        for reply in thread:
            reply.ticket_id = ticket_id
            reply.status = InteractionStatus.ASSIGNED

        await self.db.flush()

    async def get_latest_inbound_email_for_ticket(
        self,
        ticket_id: UUID,
    ) -> Interaction | None:
        """
        The most recent INBOUND email interaction on a ticket —
        used to build a reply's envelope (recipient address,
        In-Reply-To header) without the caller needing to know the
        ticket's email history.
        """

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.ticket_id == ticket_id,
                Interaction.interaction_type == "EMAIL",
            )
            .order_by(Interaction.created_at.desc())
            .limit(1)
        )

        return result.scalar_one_or_none()

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
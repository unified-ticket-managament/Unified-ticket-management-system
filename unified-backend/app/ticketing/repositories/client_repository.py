# client_repository.py

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.client import Client
from app.ticketing.schemas.client import ClientCreate


class ClientRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: ClientCreate) -> Client:
        client = Client(
            name=data.name,
            inbox_email=data.inbox_email.lower(),
            account_manager_id=data.account_manager_id,
        )
        self.db.add(client)
        await self.db.flush()
        await self.db.refresh(client)
        return client

    async def get_by_id(self, client_id: UUID) -> Client | None:
        result = await self.db.execute(
            select(Client).where(Client.client_id == client_id)
        )
        return result.scalar_one_or_none()

    async def get_active_by_inbox_email(self, inbox_email: str) -> Client | None:
        result = await self.db.execute(
            select(Client).where(
                func.lower(Client.inbox_email) == inbox_email.lower(),
                Client.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_inbox_email(self, inbox_email: str) -> Client | None:
        """
        Same lookup as get_active_by_inbox_email but without the
        is_active filter — used for the onboarding duplicate check,
        which should also reject re-using a deactivated client's
        address.
        """

        result = await self.db.execute(
            select(Client).where(func.lower(Client.inbox_email) == inbox_email.lower())
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Client]:
        result = await self.db.execute(
            select(Client).order_by(Client.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_ids(self, client_ids: list[UUID]) -> list[Client]:
        """
        Batch fetch — used by the SLA sweep to resolve every crossed-
        threshold clock's owning client in one query instead of a
        get_by_id call per clock, same convention as
        TicketRepository.list_by_ids.
        """

        if not client_ids:
            return []

        result = await self.db.execute(
            select(Client).where(Client.client_id.in_(client_ids))
        )
        return list(result.scalars().all())

    async def get_names_by_ids(self, client_ids: list[UUID]) -> dict[UUID, str]:
        """
        Batch-resolves client_id -> company name in one query — used
        by TicketService._attach_names to enrich a page of tickets
        without a get_by_id call per distinct client_company_id.
        """

        if not client_ids:
            return {}

        result = await self.db.execute(
            select(Client.client_id, Client.name).where(Client.client_id.in_(client_ids))
        )
        return dict(result.all())

    async def list_client_ids_by_account_manager(
        self, account_manager_id: UUID
    ) -> list[UUID]:
        """
        Every client this Account Manager owns — the scope boundary
        for their ticket/inbox visibility.
        """

        result = await self.db.execute(
            select(Client.client_id).where(
                Client.account_manager_id == account_manager_id
            )
        )
        return list(result.scalars().all())

# client_repository.py

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.schemas.client import ClientCreate


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

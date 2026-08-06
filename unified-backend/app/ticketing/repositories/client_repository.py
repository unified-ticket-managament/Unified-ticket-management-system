# client_repository.py

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.client import Client
from app.ticketing.models.client_contact import ClientContact
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

    async def get_active_by_any_email(self, email: str) -> Client | None:
        """
        Same intent as get_active_by_inbox_email, widened to also match
        any of a client's known contact addresses (ClientContact.email)
        — not just the single Client.inbox_email column. A client
        company routinely emails in from more than one person/address
        (e.g. APM has ~17 known contacts, only one of which is its
        inbox_email); every one of them should still resolve to the
        same Client, and therefore the same Account Manager. The
        inbox_email match is tried first, unchanged, so existing
        behavior for that address is exactly preserved; only a miss
        there falls through to the contacts table.

        If the same address were ever associated with more than one
        Client (a data-quality issue, not something this app
        prevents), this deterministically prefers a contact marked
        is_primary, then the oldest client, rather than resolving
        ambiguously.
        """

        client = await self.get_active_by_inbox_email(email)
        if client is not None:
            return client

        normalized = email.strip().lower()
        result = await self.db.execute(
            select(Client)
            .join(ClientContact, ClientContact.client_id == Client.client_id)
            .where(
                Client.is_active.is_(True),
                func.lower(ClientContact.email) == normalized,
            )
            .order_by(ClientContact.is_primary.desc(), Client.created_at.asc())
            .limit(1)
        )
        return result.scalars().first()

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

    async def update_linked_fields(
        self,
        client: Client,
        *,
        name: str | None = None,
        inbox_email: str | None = None,
        account_manager_id: UUID | None = None,
        is_active: bool | None = None,
    ) -> Client:
        """
        Patches only the fields actually passed on an existing client
        row — used by UserService's "Client" role branch (create/edit/
        activate/deactivate a Client user via the Users page routes
        straight to this table, see root CLAUDE.md's Client-role
        section) so a partial edit never clobbers a value the caller
        didn't mean to change.
        """

        if name is not None:
            client.name = name
        if inbox_email is not None:
            client.inbox_email = inbox_email.lower()
        if account_manager_id is not None:
            client.account_manager_id = account_manager_id
        if is_active is not None:
            client.is_active = is_active

        await self.db.flush()
        await self.db.refresh(client)
        return client

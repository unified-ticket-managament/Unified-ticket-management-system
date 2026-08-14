# client_service.py

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.enums import AuditEntityType, AuditEventType
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.client import (
    ClientContactResponse,
    ClientCreate,
    ClientDetailsResponse,
    ClientResponse,
)
from app.ticketing.schemas.payloads.email_payload import EmailPayload
from app.ticketing.services.access_control import ACCOUNT_MANAGER_ROLE_NAME
from app.ticketing.services.audit_log_service import AuditLogService


class ClientService:
    """
    Client (company) onboarding — the entity that maps a real client
    email address (see Client model's own docstring for what address
    this actually is, which depends on transport) to an owning Account
    Manager. Every inbound email is resolved against this table before
    anything else happens.
    """

    def __init__(
        self,
        client_repository: ClientRepository,
        user_repository: UserRepository,
        interaction_repository: InteractionRepository | None = None,
    ):
        self.client_repository = client_repository
        self.user_repository = user_repository
        self.interaction_repository = interaction_repository

    async def create(
        self,
        request: ClientCreate,
        current_user: User,
    ) -> ClientResponse:
        existing = await self.client_repository.get_by_inbox_email(
            request.inbox_email
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This inbox address is already assigned to a client.",
            )

        manager = await self.user_repository.get_by_id(request.account_manager_id)
        if (
            manager is None
            or not manager.is_active
            or manager.role.name != ACCOUNT_MANAGER_ROLE_NAME
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account manager must be an active user with the Account Manager role.",
            )

        client = await self.client_repository.create(request)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await AuditLogService.log_event(
            self.client_repository.db,
            entity_type=AuditEntityType.CLIENT,
            entity_id=client.client_id,
            event_type=AuditEventType.CLIENT_CREATED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={
                "name": client.name,
                "inbox_email": client.inbox_email,
                "account_manager_id": client.account_manager_id,
            },
        )

        return ClientResponse(
            client_id=client.client_id,
            name=client.name,
            inbox_email=client.inbox_email,
            account_manager_id=client.account_manager_id,
            is_active=client.is_active,
            created_at=client.created_at,
            account_manager_name=manager.name,
            account_manager_active=True,
        )

    async def list_all(self) -> list[ClientResponse]:
        clients = await self.client_repository.list_all()

        manager_ids = [client.account_manager_id for client in clients]
        names = await self.user_repository.get_names_by_ids(manager_ids)
        active_manager_ids = await self.user_repository.get_active_account_manager_ids(
            manager_ids
        )

        return [
            ClientResponse(
                client_id=client.client_id,
                name=client.name,
                inbox_email=client.inbox_email,
                account_manager_id=client.account_manager_id,
                is_active=client.is_active,
                created_at=client.created_at,
                account_manager_name=names.get(client.account_manager_id),
                account_manager_active=client.account_manager_id in active_manager_ids,
            )
            for client in clients
        ]

    async def get_details(self, client_id) -> ClientDetailsResponse:
        """
        Aggregated single-client detail view backing
        GET /clients/{id}/details — the Roles page's Client-tab expand
        action, gated by client:view. Reuses ClientRepository.get_by_id
        plus the same name/active-manager batch-resolution list_all
        already does, and list_contacts' own configured_only=True
        branch — no new query logic beyond what already exists.
        """

        client = await self.client_repository.get_by_id(client_id)
        if client is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client not found.",
            )

        names = await self.user_repository.get_names_by_ids(
            [client.account_manager_id]
        )
        active_manager_ids = await self.user_repository.get_active_account_manager_ids(
            [client.account_manager_id]
        )
        contacts = await self.list_contacts(client_id, configured_only=True)

        return ClientDetailsResponse(
            client_id=client.client_id,
            name=client.name,
            inbox_email=client.inbox_email,
            account_manager_id=client.account_manager_id,
            is_active=client.is_active,
            created_at=client.created_at,
            account_manager_name=names.get(client.account_manager_id),
            account_manager_active=client.account_manager_id in active_manager_ids,
            contacts=contacts,
        )

    async def list_contacts(
        self, client_id, configured_only: bool = False
    ) -> list[ClientContactResponse]:
        """
        Every known contact address for a client company — merges two
        sources rather than relying on just one:

        - The configured `client_contacts` table (seeded from the
          official org-data import, see ClientContact's own
          docstring) — the authoritative "who's a real contact at
          this company" list, listed first, independent of whether
          they've actually emailed the shared inbox yet. This is what
          backs Compose's "To" dropdown once a client is picked.
        - Every distinct personal address this client has actually
          emailed our shared inbox from, most-recently-used first —
          picks up a real contact who wrote in but isn't (yet, or
          never was) in the configured list, and is also the only
          source with a display name (EmailPayload.from_name),
          layered onto a configured-list match by email when present.

        Backs both reply composers' "To" picker (an agent isn't
        limited to whoever happened to send the thread being replied
        to) and Compose's own "To" picker.

        `configured_only=True` skips the interaction-derived merge
        entirely and returns exactly the curated `client_contacts`
        rows — used by the Users/Clients admin UI's Edit Client form
        to prefill its contact-email list. That form's Save writes a
        full-replace of whatever it displays (see
        UserService._update_client_user's `contact_emails` handling),
        so prefilling it with the merged, interaction-derived set
        would silently promote every random person who ever emailed
        in into a permanent configured contact on the next save.
        """

        if configured_only:
            configured = await self.client_repository.list_contacts_by_client_id(client_id)
            return [ClientContactResponse(email=contact.email, name=None) for contact in configured]

        interaction_names: dict[str, str | None] = {}
        if self.interaction_repository is not None:
            emails = await self.interaction_repository.list_inbound_emails_for_client(
                client_id
            )
            for interaction in emails:
                try:
                    payload = EmailPayload.model_validate(interaction.payload)
                except Exception:
                    continue

                if not payload.from_email or payload.from_email in interaction_names:
                    continue

                interaction_names[payload.from_email] = payload.from_name

        seen: set[str] = set()
        contacts: list[ClientContactResponse] = []

        configured = await self.client_repository.list_contacts_by_client_id(client_id)
        for contact in configured:
            if contact.email in seen:
                continue
            seen.add(contact.email)
            contacts.append(
                ClientContactResponse(
                    email=contact.email, name=interaction_names.get(contact.email)
                )
            )

        for email, name in interaction_names.items():
            if email in seen:
                continue
            seen.add(email)
            contacts.append(ClientContactResponse(email=email, name=name))

        return contacts

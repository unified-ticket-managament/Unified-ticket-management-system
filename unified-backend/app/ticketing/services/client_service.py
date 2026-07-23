# client_service.py

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.enums import AuditEntityType, AuditEventType
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.client import ClientContactResponse, ClientCreate, ClientResponse
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

    async def list_contacts(self, client_id) -> list[ClientContactResponse]:
        """
        Every distinct personal address this client company has ever
        emailed our shared inbox from, most-recently-used first —
        backs the reply composer's "To" picker so an agent can
        address a reply to any contact who has actually written in,
        not only whoever happened to send the one thread being
        replied to.
        """

        if self.interaction_repository is None:
            return []

        emails = await self.interaction_repository.list_inbound_emails_for_client(
            client_id
        )

        seen: set[str] = set()
        contacts: list[ClientContactResponse] = []
        for interaction in emails:
            try:
                payload = EmailPayload.model_validate(interaction.payload)
            except Exception:
                continue

            if not payload.from_email or payload.from_email in seen:
                continue

            seen.add(payload.from_email)
            contacts.append(
                ClientContactResponse(email=payload.from_email, name=payload.from_name)
            )

        return contacts

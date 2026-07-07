# ticket_service.py


from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.enums import AuditEntityType, AuditEventType
from app.models.ticket import Ticket
from app.repositories.client_repository import ClientRepository
from app.repositories.ticket_repository import (
    TicketRepository,
)
from app.repositories.user_repository import UserRepository
from app.schemas.ticket import (
    TicketCreate,
    TicketResponse,
    TicketUpdate,
)
from app.services.access_control import (
    ACCOUNT_MANAGER_ROLE_NAME,
    CATEGORY_SCOPED_ROLE_NAMES,
    ensure_agent_can_view_ticket,
)
from app.services.audit_log_service import AuditLogService


class TicketService:
    """
    Service layer for Ticket CRUD operations.
    """

    def __init__(
        self,
        ticket_repository: TicketRepository,
        user_repository: UserRepository,
        client_repository: ClientRepository | None = None,
    ):
        self.ticket_repository = ticket_repository
        self.user_repository = user_repository
        self.client_repository = client_repository

    # ---------------------------------------------------------
    # Name Enrichment
    # ---------------------------------------------------------

    async def _attach_names(self, tickets: list[Ticket]) -> None:
        """
        Resolves client_id / agent_id to display names and sets
        them as transient attributes so TicketResponse.model_validate
        (from_attributes=True) can pick them up. Not persisted.

        client_id is the legacy `users` FK (nullable now, only ever
        set on tickets created before the client-company model);
        client_company_id is the current one, resolved separately
        against the `clients` table.
        """

        user_ids = {ticket.client_id for ticket in tickets if ticket.client_id is not None}
        user_ids.update(
            ticket.agent_id for ticket in tickets if ticket.agent_id is not None
        )
        user_ids.update(
            ticket.created_by for ticket in tickets if ticket.created_by is not None
        )

        names = await self.user_repository.get_names_by_ids(list(user_ids))

        client_names: dict[UUID, str] = {}
        if self.client_repository is not None:
            for company_id in {
                t.client_company_id for t in tickets if t.client_company_id is not None
            }:
                client = await self.client_repository.get_by_id(company_id)
                if client is not None:
                    client_names[company_id] = client.name

        for ticket in tickets:
            ticket.client_name = (
                names.get(ticket.client_id) if ticket.client_id else None
            )
            ticket.client_company_name = (
                client_names.get(ticket.client_company_id)
                if ticket.client_company_id
                else None
            )
            ticket.agent_name = (
                names.get(ticket.agent_id) if ticket.agent_id else None
            )
            ticket.created_by_name = (
                names.get(ticket.created_by) if ticket.created_by else None
            )

    # ---------------------------------------------------------
    # Create Ticket
    # ---------------------------------------------------------

    async def create(
        self,
        request: TicketCreate,
    ) -> TicketResponse:

        ticket = await self.ticket_repository.create(
            request
        )

        await self._attach_names([ticket])

        return TicketResponse.model_validate(
            ticket
        )

    # ---------------------------------------------------------
    # Account Manager Scoping
    # ---------------------------------------------------------

    async def _resolve_owned_client_ids(
        self, current_user: User
    ) -> list[UUID] | None:
        """
        None = unrestricted (every other role — Team Lead/Staff stay
        unrestricted until category-based routing is defined; Super
        Admin/Site Lead have full oversight by design). A list
        (possibly empty) restricts to tickets whose client_company_id
        is in it — the Account Manager sees only their own clients.
        """

        if current_user.role.name != ACCOUNT_MANAGER_ROLE_NAME:
            return None

        if self.client_repository is None:
            return []

        return await self.client_repository.list_client_ids_by_account_manager(
            current_user.user_id
        )

    # ---------------------------------------------------------
    # Team Lead / Staff Category Scoping
    # ---------------------------------------------------------

    def _resolve_category_ticket_types(
        self, current_user: User
    ) -> list[str] | None:
        """
        None = unrestricted (Account Manager, Site Lead, Super Admin —
        Account Manager is scoped separately, above). A list (possibly
        empty) restricts to tickets whose ticket_type is in it — each
        Team Lead/Staff sees only their own work-specialization
        category's shared pool. No DB lookup needed: current_user.category
        is already eager-loaded by UserRepository.get_by_id.
        """

        if current_user.role.name not in CATEGORY_SCOPED_ROLE_NAMES:
            return None

        if current_user.category is None:
            return []

        return [current_user.category.category_name.value]

    # ---------------------------------------------------------
    # Get Ticket By ID
    # ---------------------------------------------------------

    async def get_by_id(
        self,
        ticket_id: UUID,
        current_user: User,
    ) -> TicketResponse:

        ticket = await self.ticket_repository.get_by_id(
            ticket_id
        )

        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )

        ensure_agent_can_view_ticket(ticket, current_user)

        owned_client_ids = await self._resolve_owned_client_ids(current_user)
        if owned_client_ids is not None and ticket.client_company_id not in owned_client_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this ticket.",
            )

        await self._attach_names([ticket])

        return TicketResponse.model_validate(
            ticket
        )

    # ---------------------------------------------------------
    # List Tickets
    # ---------------------------------------------------------

    async def list_all(
        self,
        current_user: User,
    ) -> list[TicketResponse]:

        # Account Manager is scoped to only their own clients' tickets
        # (see _resolve_owned_client_ids); Team Lead/Staff are scoped
        # to their own work-specialization category's shared pool
        # (see _resolve_category_ticket_types) — each category's
        # unclaimed and other-agents'-claimed tickets are browsable
        # within that category, not just "mine or unassigned". Site
        # Lead/Super Admin remain fully unrestricted.
        owned_client_ids = await self._resolve_owned_client_ids(current_user)
        ticket_types = self._resolve_category_ticket_types(current_user)
        tickets = await self.ticket_repository.list_all(
            client_company_ids=owned_client_ids,
            ticket_types=ticket_types,
        )

        await self._attach_names(tickets)

        return [
            TicketResponse.model_validate(ticket)
            for ticket in tickets
        ]

    # ---------------------------------------------------------
    # Update Ticket
    # ---------------------------------------------------------

    async def update(
        self,
        ticket_id: UUID,
        request: TicketUpdate,
        current_user: User,
    ) -> TicketResponse:

        ticket = await self.ticket_repository.get_by_id(
            ticket_id
        )

        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )

        # Snapshot only the safe, structured fields actually being
        # changed. custom_fields is caller-defined/arbitrary content
        # and is deliberately excluded from the audit trail.
        changed_fields = request.model_dump(exclude_unset=True)
        changed_fields.pop("custom_fields", None)
        old_values = {field: getattr(ticket, field) for field in changed_fields}

        ticket = await self.ticket_repository.update(
            ticket,
            request,
        )

        if changed_fields:
            actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
                current_user
            )

            await AuditLogService.log_event(
                self.ticket_repository.db,
                entity_type=AuditEntityType.TICKET,
                entity_id=ticket.ticket_id,
                event_type=AuditEventType.TICKET_UPDATED,
                actor_id=actor_id,
                actor_name=actor_name,
                actor_role=actor_role,
                old_values=old_values,
                new_values=changed_fields,
            )

        await self._attach_names([ticket])

        return TicketResponse.model_validate(
            ticket
        )

    # ---------------------------------------------------------
    # Delete Ticket
    # ---------------------------------------------------------

    async def delete(
        self,
        ticket_id: UUID,
    ) -> None:

        ticket = await self.ticket_repository.get_by_id(
            ticket_id
        )

        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )

        await self.ticket_repository.delete(
            ticket
        )

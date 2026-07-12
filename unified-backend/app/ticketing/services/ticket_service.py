# ticket_service.py


from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.enums import AuditEntityType, AuditEventType
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.audit_log_repository import AuditLogRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_relation_repository import TicketRelationRepository
from app.ticketing.repositories.ticket_repository import (
    TicketRepository,
)
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.audit_log import TicketAuditLogResponse
from app.ticketing.schemas.interaction import TicketInteractionResponse
from app.ticketing.services.audit_to_interaction import (
    SYNTHESIZABLE_EVENT_TYPES,
    synthesize_interaction_from_audit,
)
from app.ticketing.services.interaction_summary import trim_payload_for_list
from app.ticketing.storage.base import StorageService
from app.ticketing.schemas.ticket import (
    RelatedTicketSummary,
    RelateTicketRequest,
    RelateTicketResponse,
    TicketCreate,
    TicketResponse,
    TicketUpdate,
    UnrelateTicketResponse,
)
from app.ticketing.services.access_control import (
    ACCOUNT_MANAGER_ROLE_NAME,
    CATEGORY_SCOPED_ROLE_NAMES,
    ensure_agent_can_view_ticket,
)
from app.ticketing.services.audit_log_service import AuditLogService


class TicketService:
    """
    Service layer for Ticket CRUD operations.
    """

    def __init__(
        self,
        ticket_repository: TicketRepository,
        user_repository: UserRepository,
        client_repository: ClientRepository | None = None,
        ticket_relation_repository: TicketRelationRepository | None = None,
        audit_log_repository: AuditLogRepository | None = None,
        interaction_repository: InteractionRepository | None = None,
        attachment_repository: AttachmentRepository | None = None,
        storage_service: StorageService | None = None,
    ):
        self.ticket_repository = ticket_repository
        self.user_repository = user_repository
        self.client_repository = client_repository
        self.ticket_relation_repository = ticket_relation_repository
        self.audit_log_repository = audit_log_repository
        self.interaction_repository = interaction_repository
        self.attachment_repository = attachment_repository
        self.storage_service = storage_service

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
            company_ids = {
                t.client_company_id for t in tickets if t.client_company_id is not None
            }
            client_names = await self.client_repository.get_names_by_ids(list(company_ids))

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

    async def _attach_related_tickets(self, ticket: Ticket) -> None:
        """
        Resolves this ticket's related tickets and sets them as a
        transient attribute, same pattern as `_attach_names`. Only
        called from `get_by_id` (detail view) — the list view has no
        use for it and this is an N+1 lookup, small in practice since
        a ticket is expected to have only a handful of related links.
        """

        if self.ticket_relation_repository is None:
            ticket.related_tickets = []
            return

        related_ids = await self.ticket_relation_repository.list_related_ticket_ids(
            ticket.ticket_id
        )

        related_tickets: list[RelatedTicketSummary] = []
        for related_id in related_ids:
            related = await self.ticket_repository.get_by_id(related_id)
            if related is not None:
                related_tickets.append(
                    RelatedTicketSummary(
                        ticket_id=related.ticket_id,
                        title=related.title,
                        current_status=related.current_status,
                    )
                )

        ticket.related_tickets = related_tickets

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
        await self._attach_related_tickets(ticket)

        return TicketResponse.model_validate(
            ticket
        )

    # ---------------------------------------------------------
    # Related Tickets
    # ---------------------------------------------------------

    async def add_related_ticket(
        self,
        ticket_id: UUID,
        request: RelateTicketRequest,
        current_user: User,
    ) -> RelateTicketResponse:
        """
        Links two tickets together — symmetric, so either ticket's
        "Related Tickets" panel shows the other one afterward. Both
        tickets must be visible to the caller (same category/client-
        ownership gate as viewing either one directly), so this can't
        be used to confirm the existence of a ticket outside your
        normal visibility.
        """

        if ticket_id == request.related_ticket_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A ticket cannot be related to itself.",
            )

        ticket = await self.ticket_repository.get_by_id(ticket_id)
        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )
        ensure_agent_can_view_ticket(ticket, current_user)

        related_ticket = await self.ticket_repository.get_by_id(request.related_ticket_id)
        if related_ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Related ticket not found.",
            )
        ensure_agent_can_view_ticket(related_ticket, current_user)

        if self.ticket_relation_repository is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Related tickets are not configured.",
            )

        already_related = await self.ticket_relation_repository.exists(
            ticket_id, request.related_ticket_id
        )
        if already_related:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="These tickets are already related.",
            )

        await self.ticket_relation_repository.create(ticket_id, request.related_ticket_id)

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.TICKET_RELATED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            new_values={"related_ticket_id": str(request.related_ticket_id)},
        )

        return RelateTicketResponse(
            ticket_id=ticket_id,
            related_ticket_id=request.related_ticket_id,
            message="Tickets linked.",
        )

    async def remove_related_ticket(
        self,
        ticket_id: UUID,
        related_ticket_id: UUID,
        current_user: User,
    ) -> UnrelateTicketResponse:

        ticket = await self.ticket_repository.get_by_id(ticket_id)
        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )
        ensure_agent_can_view_ticket(ticket, current_user)

        if self.ticket_relation_repository is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Related tickets are not configured.",
            )

        deleted = await self.ticket_relation_repository.delete(ticket_id, related_ticket_id)
        if deleted == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="These tickets are not related.",
            )

        actor_id, actor_name, actor_role = AuditLogService.resolve_agent_actor(
            current_user
        )

        await AuditLogService.log_event(
            self.ticket_repository.db,
            entity_type=AuditEntityType.TICKET,
            entity_id=ticket_id,
            event_type=AuditEventType.TICKET_UNRELATED,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values={"related_ticket_id": str(related_ticket_id)},
        )

        return UnrelateTicketResponse(message="Tickets unlinked.")

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
    # List Audit Logs Across Every Visible Ticket
    # ---------------------------------------------------------

    async def list_all_audit_logs(
        self,
        current_user: User,
    ) -> list[TicketAuditLogResponse]:
        """
        Same visibility scoping as list_all, but returns every audit-
        log row for every ticket in that scope in one query — the
        Audit Log page used to call GET /tickets then one
        GET /tickets/{id}/audit-logs per ticket (an N+1 HTTP pattern
        repeated on every page load and every poll tick); this
        collapses that to two requests total.
        """

        owned_client_ids = await self._resolve_owned_client_ids(current_user)
        ticket_types = self._resolve_category_ticket_types(current_user)
        tickets = await self.ticket_repository.list_all(
            client_company_ids=owned_client_ids,
            ticket_types=ticket_types,
        )

        if not tickets or self.audit_log_repository is None:
            return []

        titles = {ticket.ticket_id: ticket.title for ticket in tickets}
        audit_logs = await self.audit_log_repository.list_by_ticket_ids(
            list(titles.keys())
        )

        responses = []
        for log in audit_logs:
            if log.entity_type == AuditEntityType.TICKET:
                ticket_id = log.entity_id
            else:
                ticket_id = UUID(str(log.new_values.get("ticket_id")))

            responses.append(
                TicketAuditLogResponse(
                    audit_id=log.audit_id,
                    entity_type=log.entity_type,
                    entity_id=log.entity_id,
                    event_type=log.event_type,
                    actor_id=log.actor_id,
                    actor_name=log.actor_name,
                    actor_role=log.actor_role,
                    old_values=log.old_values,
                    new_values=log.new_values,
                    created_at=log.created_at,
                    ticket_id=ticket_id,
                    ticket_title=titles.get(ticket_id, "Unknown"),
                )
            )

        return responses

    # ---------------------------------------------------------
    # List Interactions Across Every Visible Ticket
    # ---------------------------------------------------------

    async def list_all_interactions(
        self,
        current_user: User,
    ) -> list[TicketInteractionResponse]:
        """
        Same visibility scoping as list_all, but returns every
        interaction across every visible ticket's timeline in one
        query — the Interactions page used to call GET /tickets then
        one GET /tickets/{id}/interactions per ticket (the same N+1
        HTTP pattern list_all_audit_logs replaced for the Audit Log
        page), which is what made that page slow to load.
        """

        owned_client_ids = await self._resolve_owned_client_ids(current_user)
        ticket_types = self._resolve_category_ticket_types(current_user)
        tickets = await self.ticket_repository.list_all(
            client_company_ids=owned_client_ids,
            ticket_types=ticket_types,
        )

        if not tickets or self.interaction_repository is None:
            return []

        await self._attach_names(tickets)
        titles = {ticket.ticket_id: ticket.title for ticket in tickets}
        client_names = {
            ticket.ticket_id: ticket.client_company_name for ticket in tickets
        }

        interactions = await self.interaction_repository.list_by_ticket_ids(
            list(titles.keys())
        )

        # Neither this cross-ticket list view nor its row rendering
        # ever shows attachments or full payload text directly (only
        # the click-to-open thread/email detail does, via a separate
        # endpoint that keeps doing full signing) — skip the
        # per-attachment signed-URL generation and full JSONB payload
        # that used to make this endpoint slow to load.
        performer_ids = [
            interaction.performed_by
            for interaction in interactions
            if interaction.performed_by is not None
        ]
        names_by_id = await self.user_repository.get_names_by_ids(performer_ids)

        rows = [
            TicketInteractionResponse(
                interaction_id=interaction.interaction_id,
                ticket_id=interaction.ticket_id,
                interaction_type=interaction.interaction_type,
                status=interaction.status,
                direction=interaction.direction,
                performed_by=interaction.performed_by,
                performed_by_name=(
                    names_by_id.get(interaction.performed_by)
                    if interaction.performed_by is not None
                    else None
                ),
                payload=trim_payload_for_list(interaction),
                is_visible=interaction.is_visible,
                removed_by=interaction.removed_by,
                removed_at=interaction.removed_at,
                message_id=interaction.message_id,
                client_id=interaction.client_id,
                parent_interaction_id=interaction.parent_interaction_id,
                received_at=interaction.received_at,
                created_at=interaction.created_at,
                attachments=[],
                conversation_id=interaction.conversation_id,
                in_reply_to_message_id=interaction.in_reply_to_message_id,
                references=interaction.references or [],
                ticket_title=titles.get(interaction.ticket_id, "Unknown"),
                client_company_name=client_names.get(interaction.ticket_id),
            )
            for interaction in interactions
        ]

        # STATUS_CHANGE/PRIORITY_CHANGE/AGENT_TRANSFER/CLAIM/EDIT_ACCESS_*
        # no longer get their own Interaction row (see
        # audit_to_interaction.py) — synthesize a display row back
        # from each ticket's audit trail so this cross-ticket view
        # keeps showing every one of them exactly as before.
        if self.audit_log_repository is not None:
            audit_logs = await self.audit_log_repository.list_by_ticket_ids(
                list(titles.keys())
            )
            for log in audit_logs:
                if log.event_type not in SYNTHESIZABLE_EVENT_TYPES:
                    continue
                ticket_id = log.entity_id
                rows.append(
                    synthesize_interaction_from_audit(
                        log,
                        ticket_id,
                        titles.get(ticket_id, "Unknown"),
                        client_names.get(ticket_id),
                    )
                )

        # Matches list_by_ticket_ids' own ascending order — the
        # Interactions page re-sorts client-side anyway, but this
        # keeps the endpoint's own ordering convention consistent.
        rows.sort(key=lambda item: item.created_at)

        return rows

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

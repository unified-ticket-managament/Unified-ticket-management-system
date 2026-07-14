# ticket_service.py


import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, union_all
from shared_models.models import User

from app.core.request_timing import record_stage, timed_stage
from app.ticketing.models.client import Client
from app.ticketing.enums import (
    AuditEntityType,
    AuditEventType,
    InteractionDirection,
    InteractionStatus,
    TicketPriority,
    TicketStatus,
)
from app.ticketing.models.ticket import Ticket
from app.ticketing.pagination import InvalidCursorError, decode_cursor, encode_cursor
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.audit_log_repository import AuditLogRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_relation_repository import TicketRelationRepository
from app.ticketing.repositories.ticket_repository import (
    OPEN_STATUSES,
    TicketRepository,
)
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.audit_log import TicketAuditLogResponse
from app.ticketing.schemas.interaction import TicketInteractionResponse
from app.ticketing.services.interaction_summary import trim_payload_for_list
from app.ticketing.storage.base import StorageService
from app.ticketing.schemas.ticket import (
    RelatedTicketSummary,
    RelateTicketRequest,
    RelateTicketResponse,
    TicketCreate,
    TicketListItemResponse,
    TicketResponse,
    TicketUpdate,
    UnrelateTicketResponse,
)
from app.ticketing.services.access_control import (
    ACCOUNT_MANAGER_ROLE_NAME,
    CATEGORY_SCOPED_ROLE_NAMES,
    ESCALATION_TAB_ROLE_NAMES,
    ensure_agent_can_view_ticket,
)
from app.ticketing.services.audit_log_service import AuditLogService

# Mirrors the frontend's InteractionsPage.tsx VISIBLE_INTERACTION_TYPES
# whitelist — client communication only, everything else (status/
# priority changes, transfers, claims, edit-access requests, attachment
# uploads) stays on the ticket's own Timeline/Audit Log. Only applied
# as a baseline restriction in list_all_interactions' paginated mode
# (see there) — the old unbounded response is left exactly as it was
# for the standalone ticketing-service frontend, which applies this
# same whitelist client-side itself.
INTERACTIONS_PAGE_VISIBLE_TYPES = ["EMAIL", "REPLY", "INTERNAL_NOTE"]


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
        user_ids.update(
            ticket.closed_by for ticket in tickets if ticket.closed_by is not None
        )

        company_ids: set[UUID] = set()
        if self.client_repository is not None:
            company_ids = {
                t.client_company_id for t in tickets if t.client_company_id is not None
            }

        names: dict[UUID, str] = {}
        client_names: dict[UUID, str] = {}

        if user_ids and company_ids:
            # One round trip instead of two sequential ones. `users`
            # and `clients` are unrelated tables but both lookups have
            # the same (id, name) shape, so a UNION ALL combines them
            # into a single statement — worth doing because every DB
            # round trip here costs several hundred ms of network
            # latency (see this session's Server-Timing
            # investigation), independent of query complexity, so
            # round-trip *count* is what dominates this stage's cost.
            stmt = union_all(
                select(User.user_id.label("id"), User.name.label("name")).where(
                    User.user_id.in_(user_ids)
                ),
                select(Client.client_id.label("id"), Client.name.label("name")).where(
                    Client.client_id.in_(company_ids)
                ),
            )
            result = await self.user_repository.db.execute(stmt)
            for row_id, row_name in result.all():
                if row_id in user_ids:
                    names[row_id] = row_name
                if row_id in company_ids:
                    client_names[row_id] = row_name
        else:
            if user_ids:
                names = await self.user_repository.get_names_by_ids(list(user_ids))
            if company_ids:
                client_names = await self.client_repository.get_names_by_ids(
                    list(company_ids)
                )

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
            ticket.closed_by_name = (
                names.get(ticket.closed_by) if ticket.closed_by else None
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

        # One batch fetch instead of a get_by_id call per related id —
        # a ticket with many related links used to cost one round trip
        # each; list_by_ids returns them all in a single query.
        related = await self.ticket_repository.list_by_ids(related_ids)
        related_by_id = {r.ticket_id: r for r in related}
        ticket.related_tickets = [
            RelatedTicketSummary(
                ticket_id=related_id,
                title=related_by_id[related_id].title,
                current_status=related_by_id[related_id].current_status,
            )
            for related_id in related_ids
            if related_id in related_by_id
        ]

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
        *,
        limit: int | None = None,
        offset: int = 0,
        status_filter: TicketStatus | None = None,
        priority_filter: TicketPriority | None = None,
        ticket_type_filter: str | None = None,
        view: str | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> tuple[list[TicketListItemResponse], int]:
        """
        `limit=None` (the default) preserves the original unbounded
        response, matching every other list endpoint in this app —
        see TicketRepository.list_all's own docstring. Passing `limit`
        (the ticket-list page's real, only-ever-used mode) switches to
        `TicketRepository.list_visible_page` instead — one JOINed
        query returning names alongside rows and `COUNT(*) OVER()` for
        the total, instead of a separate `_attach_names` round trip —
        see that method's own docstring. `view` ("pool"/"mine"/"all")
        is this page's own tab filter, resolved against the caller's
        own id for "mine"; it costs nothing extra since it's just
        another WHERE condition on the same query. `view == "escalated"`
        is gated to ESCALATION_TAB_ROLE_NAMES — anyone else asking for
        it gets an empty result rather than a 403, matching this
        method's existing "sees nothing" convention for out-of-scope
        requests elsewhere (e.g. an Account Manager who owns no
        clients) rather than surfacing a new error shape for this one
        tab specifically.
        """

        if view == "escalated" and current_user.role.name not in ESCALATION_TAB_ROLE_NAMES:
            return [], 0

        # Account Manager is scoped to only their own clients' tickets;
        # Team Lead/Staff are scoped to their own work-specialization
        # category's shared pool (see _resolve_category_ticket_types)
        # — each category's unclaimed and other-agents'-claimed
        # tickets are browsable within that category, not just "mine
        # or unassigned". Site Lead/Super Admin remain unrestricted.
        ticket_types = self._resolve_category_ticket_types(current_user)

        if limit is not None:
            account_manager_id = (
                current_user.user_id
                if current_user.role.name == ACCOUNT_MANAGER_ROLE_NAME
                else None
            )
            page = await self.ticket_repository.list_visible_page(
                account_manager_id=account_manager_id,
                ticket_types=ticket_types,
                limit=limit,
                offset=offset,
                status_filter=status_filter,
                priority_filter=priority_filter,
                ticket_type_filter=ticket_type_filter,
                view=view,
                assigned_to=current_user.user_id,
                search=search,
                date_from=date_from,
                date_to=date_to,
                sort_by=sort_by,
                sort_dir=sort_dir,
            )

            rows = [
                TicketListItemResponse(
                    ticket_id=ticket.ticket_id,
                    client_id=ticket.client_id,
                    client_company_id=ticket.client_company_id,
                    agent_id=ticket.agent_id,
                    created_by=ticket.created_by,
                    title=ticket.title,
                    ticket_type=ticket.ticket_type,
                    current_status=ticket.current_status,
                    current_priority=ticket.current_priority,
                    version=ticket.version,
                    closed_at=ticket.closed_at,
                    created_at=ticket.created_at,
                    updated_at=ticket.updated_at,
                    client_name=client_name,
                    client_company_name=client_company_name,
                    agent_name=agent_name,
                    created_by_name=created_by_name,
                    is_escalated=escalation_status is not None,
                    escalation_level=escalation_level,
                    escalation_status=escalation_status,
                    escalation_ack_due_at=escalation_ack_due_at,
                    resolution_sla_tier=resolution_sla_tier,
                )
                for (
                    ticket,
                    client_name,
                    client_company_name,
                    agent_name,
                    created_by_name,
                    escalation_level,
                    escalation_status,
                    escalation_ack_due_at,
                    resolution_sla_tier,
                    *_,
                ) in page.items
            ]
            return rows, page.total

        owned_client_ids = await self._resolve_owned_client_ids(current_user)
        tickets, total = await self.ticket_repository.list_all(
            client_company_ids=owned_client_ids,
            ticket_types=ticket_types,
        )

        await self._attach_names(tickets)

        # TicketListItemResponse (not TicketResponse) — drops
        # `custom_fields`/`related_tickets`, neither of which any list
        # view reads (the latter isn't even populated here — see
        # TicketListItemResponse's own docstring).
        return [
            TicketListItemResponse.model_validate(ticket)
            for ticket in tickets
        ], total

    async def count_by_view(self, current_user: User) -> dict[str, int]:
        """
        The ticket-list page's four tab badges (Open Pool / My
        Tickets / All / Escalated) in one grouped query — see
        TicketRepository.count_by_view. `escalated` is forced to 0 for
        anyone outside ESCALATION_TAB_ROLE_NAMES, same "sees nothing"
        convention list_all's own `view == "escalated"` gate uses —
        showing a nonzero badge for a tab the caller can't open would
        be a confusing UI state, so this is overridden here rather
        than trusting the repository's raw (role-blind) count.
        """

        ticket_types = self._resolve_category_ticket_types(current_user)
        account_manager_id = (
            current_user.user_id
            if current_user.role.name == ACCOUNT_MANAGER_ROLE_NAME
            else None
        )
        counts = await self.ticket_repository.count_by_view(
            account_manager_id=account_manager_id,
            ticket_types=ticket_types,
            assigned_to=current_user.user_id,
        )

        if current_user.role.name not in ESCALATION_TAB_ROLE_NAMES:
            counts["escalated"] = 0

        return counts

    async def get_dashboard_stats(self, current_user: User) -> dict:
        """
        Everything the ticket-workspace Dashboard needs: eight stat-
        card counts (one grouped SQL query, see
        TicketRepository.dashboard_stats) plus two small bounded ticket
        lists (recent — most recently updated 6, regardless of status;
        critical — open, HIGH-priority, most recently updated 5) via
        the same list_visible_page query the ticket-list page uses.
        This used to be `listTickets()` — every visible ticket,
        unbounded — fetched just so the browser could compute all of
        this client-side; that gets strictly slower and heavier as the
        ticket count grows, while this endpoint's cost stays bounded
        regardless of how many tickets exist.
        """

        ticket_types = self._resolve_category_ticket_types(current_user)
        account_manager_id = (
            current_user.user_id
            if current_user.role.name == ACCOUNT_MANAGER_ROLE_NAME
            else None
        )

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        sla_risk_cutoff = now - timedelta(hours=24)

        stats = await self.ticket_repository.dashboard_stats(
            account_manager_id=account_manager_id,
            ticket_types=ticket_types,
            today_start=today_start,
            sla_risk_cutoff=sla_risk_cutoff,
        )

        recent_page = await self.ticket_repository.list_visible_page(
            account_manager_id=account_manager_id,
            ticket_types=ticket_types,
            limit=6,
            sort_by="updated_at",
            sort_dir="desc",
        )
        # HIGH-priority tickets bounded to a small page, then narrowed
        # to still-open ones and trimmed to 5 in Python — a second
        # `current_status IN (...)` condition isn't worth adding to
        # list_visible_page for this one caller; 20 HIGH-priority rows
        # is already a small, bounded fetch regardless of how many
        # tickets of every other priority exist.
        critical_candidates = await self.ticket_repository.list_visible_page(
            account_manager_id=account_manager_id,
            ticket_types=ticket_types,
            limit=20,
            priority_filter=TicketPriority.HIGH,
            sort_by="updated_at",
            sort_dir="desc",
        )
        open_statuses = set(OPEN_STATUSES)
        critical_rows = [
            row for row in critical_candidates.items if row[0].current_status in open_statuses
        ][:5]

        # Each row is (Ticket, client_name, client_company_name,
        # agent_name, created_by_name, full_count) — already fully
        # enriched by list_visible_page's own joins, so this builds
        # the response directly instead of a second _attach_names
        # round trip (which would defeat the point of that join).
        def _to_summary(row) -> TicketListItemResponse:
            (
                ticket,
                client_name,
                client_company_name,
                agent_name,
                created_by_name,
                escalation_level,
                escalation_status,
                escalation_ack_due_at,
                resolution_sla_tier,
                *_,
            ) = row
            return TicketListItemResponse(
                ticket_id=ticket.ticket_id,
                client_id=ticket.client_id,
                client_company_id=ticket.client_company_id,
                agent_id=ticket.agent_id,
                created_by=ticket.created_by,
                title=ticket.title,
                ticket_type=ticket.ticket_type,
                current_status=ticket.current_status,
                current_priority=ticket.current_priority,
                version=ticket.version,
                closed_at=ticket.closed_at,
                created_at=ticket.created_at,
                updated_at=ticket.updated_at,
                client_name=client_name,
                client_company_name=client_company_name,
                agent_name=agent_name,
                created_by_name=created_by_name,
                is_escalated=escalation_status is not None,
                escalation_level=escalation_level,
                escalation_status=escalation_status,
                escalation_ack_due_at=escalation_ack_due_at,
                resolution_sla_tier=resolution_sla_tier,
            )

        return {
            **stats,
            "recent_tickets": [_to_summary(row) for row in recent_page.items],
            "critical_tickets": [_to_summary(row) for row in critical_rows],
        }

    async def get_sla_overview_counts(self, current_user: User) -> dict[str, int]:
        """
        Dashboard "SLA Overview" tile counts — one grouped query (see
        TicketRepository.sla_overview_counts) under the same
        visibility scoping as get_dashboard_stats above, replacing the
        old N+1 pattern (GET /tickets unbounded, then one
        GET /tickets/{id}/sla call per visible ticket) that used to
        back this same tile client-side.
        """

        ticket_types = self._resolve_category_ticket_types(current_user)
        account_manager_id = (
            current_user.user_id
            if current_user.role.name == ACCOUNT_MANAGER_ROLE_NAME
            else None
        )

        return await self.ticket_repository.sla_overview_counts(
            account_manager_id=account_manager_id,
            ticket_types=ticket_types,
            now=datetime.now(timezone.utc),
        )

    # ---------------------------------------------------------
    # List Audit Logs Across Every Visible Ticket
    # ---------------------------------------------------------

    async def list_all_audit_logs(
        self,
        current_user: User,
        *,
        limit: int | None = None,
        offset: int = 0,
        entity_type: AuditEntityType | None = None,
        event_type: AuditEventType | None = None,
        actor_name: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
    ) -> tuple[list[TicketAuditLogResponse], int]:
        """
        Same visibility scoping as list_all, but returns every audit-
        log row for every ticket in that scope in one query — the
        Audit Log page used to call GET /tickets then one
        GET /tickets/{id}/audit-logs per ticket (an N+1 HTTP pattern
        repeated on every page load and every poll tick); this
        collapses that to two requests total.

        `limit=None` (the default) preserves the original unbounded
        response. Passing `limit` bounds the query and reports the
        true filtered total in the second return value — this matters
        more here than almost anywhere else in the app, since the
        Audit Log page polls this endpoint every 15 seconds (see
        AuditLogRepository.list_by_ticket_ids's own docstring).
        `search` matches ticket title — resolved here (not pushed into
        the audit-log query as a join) since titles are already
        fetched in-process for the whole visible ticket set below.
        """

        if self.audit_log_repository is None:
            return [], 0

        if limit is not None:
            account_manager_id = (
                current_user.user_id
                if current_user.role.name == ACCOUNT_MANAGER_ROLE_NAME
                else None
            )
            ticket_types = self._resolve_category_ticket_types(current_user)

            page = await self.audit_log_repository.list_visible_page(
                account_manager_id=account_manager_id,
                ticket_types=ticket_types,
                limit=limit,
                offset=offset,
                entity_type=entity_type,
                event_type=event_type,
                actor_name=actor_name,
                date_from=date_from,
                date_to=date_to,
                search=search,
            )

            responses = [
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
                    ticket_id=log.ticket_id,
                    ticket_title=ticket_title or "Unknown",
                )
                for log, ticket_title, *_ in page.items
            ]

            return responses, page.total

        # Unbounded fallback (limit=None) — preserved for any caller
        # that still wants the original every-visible-row response
        # (see this method's own docstring above and
        # TicketRepository.list_all's docstring on why `limit=None`
        # is kept working everywhere in this app). Still pays for the
        # unbounded ticket_repository.list_all fetch this method used
        # to always pay for — but only on this now-rarely-exercised
        # path, not on every request/poll tick.
        owned_client_ids = await self._resolve_owned_client_ids(current_user)
        ticket_types = self._resolve_category_ticket_types(current_user)
        tickets, _ = await self.ticket_repository.list_all(
            client_company_ids=owned_client_ids,
            ticket_types=ticket_types,
        )

        if not tickets:
            return [], 0

        titles = {ticket.ticket_id: ticket.title for ticket in tickets}
        ticket_ids = list(titles.keys())

        if search:
            term = search.lower()
            ticket_ids = [
                ticket_id
                for ticket_id in ticket_ids
                if term in titles.get(ticket_id, "").lower()
            ]
            if not ticket_ids:
                return [], 0

        audit_logs, total = await self.audit_log_repository.list_by_ticket_ids(
            ticket_ids,
            limit=None,
            offset=offset,
            entity_type=entity_type,
            event_type=event_type,
            actor_name=actor_name,
            date_from=date_from,
            date_to=date_to,
        )

        responses = []
        for log in audit_logs:
            # Every row here matched the `ticket_id IN (...)` filter
            # list_by_ticket_ids just ran, so it's always set — no
            # more per-row re-derivation from entity_type/new_values.
            ticket_id = log.ticket_id

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

        return responses, total

    # ---------------------------------------------------------
    # List Interactions Across Every Visible Ticket
    # ---------------------------------------------------------

    async def list_all_interactions(
        self,
        current_user: User,
        *,
        limit: int | None = None,
        offset: int = 0,
        cursor: str | None = None,
        interaction_type: str | None = None,
        direction: InteractionDirection | None = None,
        interaction_status: InteractionStatus | None = None,
        agent_id: UUID | None = None,
        ticket_id: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
    ) -> tuple[list[TicketInteractionResponse], int, str | None]:
        """
        Same visibility scoping as list_all, but returns every
        interaction across every visible ticket's timeline in one
        query — the Interactions page used to call GET /tickets then
        one GET /tickets/{id}/interactions per ticket (the same N+1
        HTTP pattern list_all_audit_logs replaced for the Audit Log
        page), which is what made that page slow to load.

        `limit=None` (the default) preserves the original unbounded,
        every-visible-interaction response — see
        InteractionRepository.list_by_ticket_ids for how these filter/
        pagination params thread through to the actual query. `cursor`
        (from a previous response's `X-Next-Cursor` header) is an
        additive keyset-paging alternative to `offset` for deep paging
        at scale — ignored unless `limit` is also given; pass either
        `cursor` or `offset`, not both (`cursor` wins if both given).
        Returns `(rows, total, next_cursor)` — `next_cursor` is `None`
        unless `limit` was given and the page came back full.
        """

        decoded_cursor: tuple | None = None
        if cursor is not None and limit is not None:
            try:
                decoded_cursor = decode_cursor(cursor)
            except InvalidCursorError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid pagination cursor.",
                ) from exc

        if limit is not None:
            return await self._list_interactions_page(
                current_user,
                limit=limit,
                offset=offset,
                cursor=decoded_cursor,
                interaction_type=interaction_type,
                direction=direction,
                interaction_status=interaction_status,
                agent_id=agent_id,
                ticket_id=ticket_id,
                date_from=date_from,
                date_to=date_to,
                search=search,
            )

        with timed_stage("visibility"):
            owned_client_ids = await self._resolve_owned_client_ids(current_user)
            ticket_types = self._resolve_category_ticket_types(current_user)
            tickets, _ = await self.ticket_repository.list_all(
                client_company_ids=owned_client_ids,
                ticket_types=ticket_types,
            )

            if ticket_id is not None:
                tickets = [t for t in tickets if t.ticket_id == ticket_id]

            if not tickets or self.interaction_repository is None:
                return [], 0, None

            await self._attach_names(tickets)

        titles = {ticket.ticket_id: ticket.title for ticket in tickets}
        client_names = {
            ticket.ticket_id: ticket.client_company_name for ticket in tickets
        }

        # list_by_ticket_ids itself splits its own internal COUNT and
        # SELECT into separate `count`/`query` Server-Timing stages —
        # see that method.
        interactions, total = await self.interaction_repository.list_by_ticket_ids(
            list(titles.keys()),
            limit=None,
            offset=offset,
            cursor=decoded_cursor,
            interaction_type=interaction_type,
            interaction_types=None,
            direction=direction,
            status=interaction_status,
            performed_by=agent_id,
            date_from=date_from,
            date_to=date_to,
            search=search,
        )

        # Neither this cross-ticket list view nor its row rendering
        # ever shows attachments or full payload text directly (only
        # the click-to-open thread/email detail does, via a separate
        # endpoint that keeps doing full signing) — skip the
        # per-attachment signed-URL generation and full JSONB payload
        # that used to make this endpoint slow to load.
        with timed_stage("enrichment"):
            performer_ids = [
                interaction.performed_by
                for interaction in interactions
                if interaction.performed_by is not None
            ]
            names_by_id = await self.user_repository.get_names_by_ids(performer_ids)

        serialization_start = time.perf_counter()
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
        # audit_to_interaction.py) — the per-ticket Timeline tab
        # synthesizes a display row for these from the ticket's audit
        # trail, but this cross-ticket view's own frontend whitelist
        # (InteractionsPage.tsx's VISIBLE_INTERACTION_TYPES) never
        # shows any of those types, so there's no point paying for the
        # extra audit-log query and synthesis here just to have the
        # client discard every row it produces.

        # Matches list_by_ticket_ids' own ascending order in this
        # (unbounded, backward-compatible) mode — the standalone
        # ticketing-service frontend's Interactions page re-sorts
        # client-side anyway, but this keeps the endpoint's own
        # ordering convention consistent for any other caller.
        rows.sort(key=lambda item: item.created_at)
        record_stage("serialization", (time.perf_counter() - serialization_start) * 1000)

        return rows, total, None

    async def _list_interactions_page(
        self,
        current_user: User,
        *,
        limit: int,
        offset: int,
        cursor: tuple | None,
        interaction_type: str | None,
        direction: InteractionDirection | None,
        interaction_status: InteractionStatus | None,
        agent_id: UUID | None,
        ticket_id: UUID | None,
        date_from: datetime | None,
        date_to: datetime | None,
        search: str | None,
    ) -> tuple[list[TicketInteractionResponse], int, str | None]:
        """
        The paginated (embedded-frontend) branch of list_all_interactions
        — see InteractionRepository.list_visible_page's own docstring
        for the full round-trip-collapsing rationale. `account_manager_id`
        and `ticket_types` below cost zero DB round trips to compute:
        the former is a plain role-name comparison against the
        already-loaded `current_user`, the latter reads
        `current_user.category`, eager-loaded at auth time — neither
        this method nor list_visible_page ever calls
        _resolve_owned_client_ids (which itself issues a real query)
        for this path anymore.
        """

        if self.interaction_repository is None:
            return [], 0, None

        account_manager_id = (
            current_user.user_id
            if current_user.role.name == ACCOUNT_MANAGER_ROLE_NAME
            else None
        )
        ticket_types = self._resolve_category_ticket_types(current_user)

        page = await self.interaction_repository.list_visible_page(
            account_manager_id=account_manager_id,
            ticket_types=ticket_types,
            ticket_id=ticket_id,
            limit=limit,
            offset=offset,
            cursor=cursor,
            interaction_type=interaction_type,
            interaction_types=INTERACTIONS_PAGE_VISIBLE_TYPES,
            direction=direction,
            status=interaction_status,
            performed_by=agent_id,
            date_from=date_from,
            date_to=date_to,
            search=search,
        )

        next_cursor = None
        if len(page.items) == limit:
            last_interaction = page.items[-1][0]
            next_cursor = encode_cursor(last_interaction.created_at, last_interaction.interaction_id)

        serialization_start = time.perf_counter()
        rows = [
            TicketInteractionResponse(
                interaction_id=interaction.interaction_id,
                ticket_id=interaction.ticket_id,
                interaction_type=interaction.interaction_type,
                status=interaction.status,
                direction=interaction.direction,
                performed_by=interaction.performed_by,
                performed_by_name=performed_by_name,
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
                ticket_title=ticket_title or "Unknown",
                client_company_name=client_company_name,
            )
            # Each row is (Interaction, ticket_title, client_company_name,
            # performed_by_name, full_count) in offset mode, or without
            # full_count in cursor mode — unpack the first four either way.
            for interaction, ticket_title, client_company_name, performed_by_name, *_ in page.items
        ]
        record_stage("serialization", (time.perf_counter() - serialization_start) * 1000)

        return rows, page.total, next_cursor

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

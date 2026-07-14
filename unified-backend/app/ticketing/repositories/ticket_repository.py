# ticket_repository.py
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from shared_models.models import User

from app.ticketing.enums import TicketPriority, TicketStatus
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket
from app.ticketing.schemas.ticket import TicketCreate, TicketUpdate

CLOSED_STATUSES = (TicketStatus.RESOLVED, TicketStatus.CLOSED)
# Every open (not yet resolved/closed) status — mirrors the frontend
# Dashboard's own OPEN_STATUSES constant. Public so
# TicketService.get_dashboard_stats can filter the bounded "critical
# tickets" candidate list against the same definition without reaching
# into a repository-internal name.
OPEN_STATUSES = (
    TicketStatus.OPEN,
    TicketStatus.IN_PROGRESS,
    TicketStatus.PENDING,
    TicketStatus.WAITING_FOR_CLIENT,
)


class TicketVisiblePage:
    """Plain result holder — see list_visible_page's own docstring."""

    __slots__ = ("items", "total")

    def __init__(self, items, total: int):
        self.items = items
        self.total = total

#ticket_repository.py
class TicketRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: TicketCreate) -> Ticket:
        ticket = Ticket(**data.model_dump())
        self.db.add(ticket)
        await self.db.flush()
        await self.db.refresh(ticket)
        return ticket

    async def get_by_id(self, ticket_id: UUID) -> Ticket | None:
        result = await self.db.execute(
            select(Ticket).where(Ticket.ticket_id == ticket_id)
        )
        return result.scalar_one_or_none()

    async def list_by_ids(self, ticket_ids: list[UUID]) -> list[Ticket]:
        """
        Batch fetch — used by InboxService.get_inbox to enrich
        ticketed inbox rows with priority/category in one query
        instead of a get_by_id call per row.
        """

        if not ticket_ids:
            return []

        result = await self.db.execute(
            select(Ticket).where(Ticket.ticket_id.in_(ticket_ids))
        )
        return list(result.scalars().all())

    # Every sortable column the ticket-list page's SortHeader offers —
    # a fixed allowlist, never interpolating a caller-supplied column
    # name directly into `order_by`.
    _SORT_COLUMNS = {
        "created_at": Ticket.created_at,
        "updated_at": Ticket.updated_at,
        "title": Ticket.title,
    }

    def _visibility_conditions(
        self,
        *,
        client_company_ids: list[UUID] | None = None,
        account_manager_id: UUID | None = None,
        ticket_types: list[str] | None = None,
        agent_ids: list[UUID] | None = None,
    ) -> list:
        """
        Account Manager scoping can be supplied either way: `list_all`
        callers already resolved a concrete `client_company_ids` list
        elsewhere (e.g. `_resolve_owned_client_ids`, itself a real
        round trip), so they pass that. `list_visible_page`/
        `count_by_view` (the ticket-list page's own hot path) instead
        pass `account_manager_id` and let this build an
        `IN (SELECT client_id FROM clients WHERE account_manager_id
        = ...)` subquery in the SAME statement — avoiding that extra
        round trip entirely, same reasoning as
        InteractionRepository.list_visible_page's identical subquery.
        An Account Manager who owns zero clients still "sees nothing"
        for free either way, no special-case needed.

        `agent_ids` is a narrower, opt-in alternative to `ticket_types`
        for a caller that wants "tickets assigned to one of these
        specific agents" rather than "tickets in this whole category
        pool" — used only by the Audit Log page's Team Lead/Staff
        scoping (see TicketService._resolve_audit_log_agent_ids) so
        that page can be scoped to one reporting line without
        narrowing `ticket_types`'s existing, unrelated category-pool
        meaning for every other caller (ticket list, interactions,
        dashboard stats).
        """

        conditions = []
        if client_company_ids is not None:
            # An empty list is a deliberate "owns no clients, sees
            # nothing" rather than "unrestricted".
            conditions.append(Ticket.client_company_id.in_(client_company_ids))
        elif account_manager_id is not None:
            owned_client_ids = select(Client.client_id).where(
                Client.account_manager_id == account_manager_id
            )
            conditions.append(Ticket.client_company_id.in_(owned_client_ids))
        if ticket_types is not None:
            # Team Lead/Staff category scoping — restrict to tickets
            # filed under their own work-specialization category. An
            # empty list is a deliberate "no category, sees nothing"
            # rather than "unrestricted", same convention as above.
            conditions.append(Ticket.ticket_type.in_(ticket_types))
        if agent_ids is not None:
            # Same "empty list means sees nothing" convention as above.
            conditions.append(Ticket.agent_id.in_(agent_ids))
        return conditions

    async def list_all(
        self,
        agent_id: UUID | None = None,
        client_company_ids: list[UUID] | None = None,
        ticket_types: list[str] | None = None,
        *,
        agent_ids: list[UUID] | None = None,
        limit: int | None = None,
        offset: int = 0,
        status_filter: TicketStatus | None = None,
        priority_filter: TicketPriority | None = None,
        ticket_type_filter: str | None = None,
        view: str | None = None,
        assigned_to: UUID | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> tuple[list[Ticket], int]:
        """
        `limit=None` (the default) preserves this method's original,
        unbounded behavior, with the second return value just
        `len(items)` — no separate COUNT needed. This is the mode
        `list_all_interactions`/`list_all_audit_logs` both still use:
        they need every visible ticket (for id-scoping/title
        resolution), not a page of them. Passing `limit` — used only
        by the ticket-list endpoint itself — switches to a bounded,
        filtered query plus a COUNT(*) over the same filters, the same
        convention used throughout this app's other list endpoints.
        `search` matches ticket title only (case-insensitive substring).

        `view`/`assigned_to`/`ticket_type_filter` are the ticket-list
        page's own three UI-level filters (Open Pool / My Tickets /
        All tabs, and the user-facing category dropdown) — distinct
        from `client_company_ids`/`ticket_types`/`agent_ids` above,
        which are role-based *visibility* scoping and always apply
        regardless of which tab is open. `view="pool"` means
        "unclaimed and OPEN"; `view="mine"` requires `assigned_to` (an
        exact agent_id match, unlike `agent_id` above which also
        matches unassigned tickets — a different, older parameter used
        for a different caller's "can this agent see it" visibility
        check, not this page's "is this mine" tab filter, and not the
        same thing as the plural `agent_ids` visibility-scoping param
        either — that one has no unassigned-tickets fallback, since an
        unclaimed ticket isn't "this reporting line's" work yet).
        `sort_by`/`sort_dir` are validated against a fixed column
        allowlist (`_SORT_COLUMNS`) so nothing caller-supplied ever
        reaches `order_by` directly.
        """

        conditions = self._visibility_conditions(
            client_company_ids=client_company_ids,
            ticket_types=ticket_types,
            agent_ids=agent_ids,
        )

        if agent_id is not None:
            # Unassigned tickets stay visible to everyone so they
            # don't become permanently invisible to any agent.
            conditions.append(
                or_(Ticket.agent_id == agent_id, Ticket.agent_id.is_(None))
            )

        if view == "pool":
            conditions.append(Ticket.agent_id.is_(None))
            conditions.append(Ticket.current_status == TicketStatus.OPEN)
        elif view == "mine" and assigned_to is not None:
            conditions.append(Ticket.agent_id == assigned_to)

        if ticket_type_filter is not None:
            conditions.append(Ticket.ticket_type == ticket_type_filter)
        if status_filter is not None:
            conditions.append(Ticket.current_status == status_filter)
        if priority_filter is not None:
            conditions.append(Ticket.current_priority == priority_filter)
        if search:
            conditions.append(Ticket.title.ilike(f"%{search}%"))
        if date_from is not None:
            conditions.append(Ticket.created_at >= date_from)
        if date_to is not None:
            conditions.append(Ticket.created_at <= date_to)

        sort_column = self._SORT_COLUMNS.get(sort_by, Ticket.created_at)
        order = sort_column.asc() if sort_dir == "asc" else sort_column.desc()

        base_query = select(Ticket).where(*conditions)

        if limit is None:
            result = await self.db.execute(base_query.order_by(order))
            items = list(result.scalars().all())
            return items, len(items)

        page_query = (
            select(Ticket, func.count().over().label("full_count"))
            .where(*conditions)
            .order_by(order)
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(page_query)
        rows = result.all()

        if rows:
            return [row[0] for row in rows], rows[0].full_count

        # Empty page — same window-function-has-no-row-to-report-on
        # fallback as InteractionRepository.list_visible_page.
        count_result = await self.db.execute(
            select(func.count()).select_from(Ticket).where(*conditions)
        )
        return [], count_result.scalar_one()

    async def count_by_view(
        self,
        *,
        account_manager_id: UUID | None,
        ticket_types: list[str] | None,
        assigned_to: UUID,
    ) -> dict[str, int]:
        """
        One grouped query, three FILTERed counts — the ticket-list
        page's tab badges (Open Pool / My Tickets / All), under the
        exact same visibility scoping `list_visible_page` applies,
        without fetching a single ticket row. Same shape as
        InteractionRepository.count_by_view (the Mail page's own tab
        badges).
        """

        conditions = self._visibility_conditions(
            account_manager_id=account_manager_id, ticket_types=ticket_types
        )

        query = select(
            func.count().filter(
                Ticket.agent_id.is_(None), Ticket.current_status == TicketStatus.OPEN
            ),
            func.count().filter(Ticket.agent_id == assigned_to),
            func.count(),
        ).where(*conditions)

        result = await self.db.execute(query)
        pool, mine, all_count = result.one()

        return {"pool": pool, "mine": mine, "all": all_count}

    async def dashboard_stats(
        self,
        *,
        account_manager_id: UUID | None,
        ticket_types: list[str] | None,
        today_start: datetime,
        sla_risk_cutoff: datetime,
    ) -> dict[str, int]:
        """
        Every stat card on the ticket-workspace Dashboard, in one
        grouped query — this used to be eight separate `.filter()`
        passes in the browser over an unbounded `listTickets()`
        response (every visible ticket, fetched just to compute eight
        numbers), which gets strictly worse as the ticket count grows.
        Same visibility scoping and grouped-FILTER shape as
        count_by_view. `today_start`/`sla_risk_cutoff` are passed in
        rather than computed here since `Date.now()`-style "current
        time" belongs in the caller, not buried in a repository query.
        """

        conditions = self._visibility_conditions(
            account_manager_id=account_manager_id, ticket_types=ticket_types
        )

        query = select(
            func.count().filter(Ticket.agent_id.isnot(None)),
            func.count().filter(Ticket.current_status.in_(OPEN_STATUSES)),
            func.count().filter(Ticket.current_status == TicketStatus.IN_PROGRESS),
            func.count().filter(Ticket.current_status.in_(CLOSED_STATUSES)),
            func.count().filter(
                Ticket.current_status.in_(CLOSED_STATUSES),
                Ticket.updated_at >= today_start,
            ),
            func.count().filter(Ticket.current_status == TicketStatus.CLOSED),
            func.count().filter(
                Ticket.current_priority == TicketPriority.HIGH,
                Ticket.current_status.in_(OPEN_STATUSES),
            ),
            func.count().filter(
                Ticket.current_status.in_(OPEN_STATUSES),
                Ticket.updated_at <= sla_risk_cutoff,
            ),
        ).where(*conditions)

        result = await self.db.execute(query)
        (
            assigned,
            open_count,
            in_progress,
            resolved,
            resolved_today,
            closed,
            critical,
            sla_risk,
        ) = result.one()

        return {
            "assigned": assigned,
            "open": open_count,
            "in_progress": in_progress,
            "resolved": resolved,
            "resolved_today": resolved_today,
            "closed": closed,
            "critical": critical,
            "sla_risk": sla_risk,
        }

    async def list_visible_page(
        self,
        *,
        account_manager_id: UUID | None,
        ticket_types: list[str] | None,
        limit: int,
        offset: int = 0,
        status_filter: TicketStatus | None = None,
        priority_filter: TicketPriority | None = None,
        ticket_type_filter: str | None = None,
        view: str | None = None,
        assigned_to: UUID | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> TicketVisiblePage:
        """
        The ticket-list page's real query — same visibility/filter/
        sort logic as list_all's bounded branch, but additionally
        LEFT JOINs the three `users` FKs a ticket carries (client_id —
        legacy, agent_id, created_by) plus `clients` (client_company_id)
        directly into the same statement, so `client_name`/`agent_name`/
        `created_by_name`/`client_company_name` come back on the same
        row instead of TicketService._attach_names' separate UNION ALL
        round trip. Three distinct aliases of `users` are needed since
        a ticket can reference three different user rows at once — a
        single unaliased join could only ever match one of them.

        `total` is `COUNT(*) OVER()`, same convention (and the same
        empty-page fallback) as InteractionRepository.list_visible_page
        and AuditLogRepository.list_visible_page.
        """

        conditions = self._visibility_conditions(
            account_manager_id=account_manager_id, ticket_types=ticket_types
        )

        if view == "pool":
            conditions.append(Ticket.agent_id.is_(None))
            conditions.append(Ticket.current_status == TicketStatus.OPEN)
        elif view == "mine" and assigned_to is not None:
            conditions.append(Ticket.agent_id == assigned_to)

        if ticket_type_filter is not None:
            conditions.append(Ticket.ticket_type == ticket_type_filter)
        if status_filter is not None:
            conditions.append(Ticket.current_status == status_filter)
        if priority_filter is not None:
            conditions.append(Ticket.current_priority == priority_filter)
        if search:
            conditions.append(Ticket.title.ilike(f"%{search}%"))
        if date_from is not None:
            conditions.append(Ticket.created_at >= date_from)
        if date_to is not None:
            conditions.append(Ticket.created_at <= date_to)

        sort_column = self._SORT_COLUMNS.get(sort_by, Ticket.created_at)
        order = sort_column.asc() if sort_dir == "asc" else sort_column.desc()

        ClientUser = aliased(User)
        AgentUser = aliased(User)
        CreatedByUser = aliased(User)

        def _base_select(*extra_columns):
            return (
                select(
                    Ticket,
                    ClientUser.name.label("client_name"),
                    Client.name.label("client_company_name"),
                    AgentUser.name.label("agent_name"),
                    CreatedByUser.name.label("created_by_name"),
                    *extra_columns,
                )
                .outerjoin(ClientUser, ClientUser.user_id == Ticket.client_id)
                .outerjoin(Client, Client.client_id == Ticket.client_company_id)
                .outerjoin(AgentUser, AgentUser.user_id == Ticket.agent_id)
                .outerjoin(CreatedByUser, CreatedByUser.user_id == Ticket.created_by)
                .where(*conditions)
            )

        page_query = (
            _base_select(func.count().over().label("full_count"))
            .order_by(order)
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(page_query)
        rows = result.all()

        if rows:
            return TicketVisiblePage(items=rows, total=rows[0].full_count)

        count_result = await self.db.execute(
            select(func.count()).select_from(Ticket).where(*conditions)
        )
        return TicketVisiblePage(items=[], total=count_result.scalar_one())

    async def update(self, ticket: Ticket, data: TicketUpdate) -> Ticket:
        update_data = data.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(ticket, field, value)

        await self.db.flush()
        await self.db.refresh(ticket)
        return ticket

    async def delete(self, ticket: Ticket) -> None:
        await self.db.delete(ticket)
        await self.db.flush()

    async def claim(self, ticket: Ticket, agent_id: UUID) -> Ticket | None:
        """
        Atomically assigns an unclaimed OPEN ticket to `agent_id` and
        moves it to IN_PROGRESS.

        Guarded by a conditional UPDATE (`agent_id IS NULL AND
        current_status = OPEN`) rather than a plain ORM attribute
        set — two agents clicking Claim on the same ticket at the
        same moment both read agent_id=None, so only a WHERE-gated
        UPDATE can guarantee just one of them wins. Returns None
        (instead of overwriting) when the guard fails, so the caller
        can turn that into a 409 rather than silently stealing the
        ticket from whoever claimed it first.
        """

        result = await self.db.execute(
            update(Ticket)
            .where(
                Ticket.ticket_id == ticket.ticket_id,
                Ticket.agent_id.is_(None),
                Ticket.current_status == TicketStatus.OPEN,
            )
            .values(agent_id=agent_id, current_status=TicketStatus.IN_PROGRESS)
        )

        if result.rowcount == 0:
            return None

        await self.db.flush()
        await self.db.refresh(ticket)

        return ticket
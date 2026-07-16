# ticket_repository.py
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, case, exists, func, literal, not_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from shared_models.models import User

from app.ticketing.enums import EscalationStatus, SLAClockStatus, TicketPriority, TicketStatus
from app.ticketing.models.client import Client
from app.ticketing.models.resolution_sla import ResolutionSLA
from app.ticketing.models.sla_policy import SLAPolicy
from app.ticketing.models.ticket import Ticket
from app.ticketing.models.ticket_escalation import TicketEscalation
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


def _resolution_sla_tier_case(now: datetime):
    """
    Classifies a ticket's Resolution SLA clock into the same 4 tiers
    (escalated/breached/at_risk/healthy) the frontend's slaMath.ts and
    sla_overview_counts below already use — same remaining-seconds-vs-
    target-seconds comparisons as sla_overview_counts (not a fraction
    division, which would divide by zero for a policy-less ticket),
    just returning a per-row label instead of aggregate counts. Caller
    must join ResolutionSLA and outerjoin SLAPolicy (on
    SLAPolicy.priority == ResolutionSLA.priority) first.

    NULL when there's no active (RUNNING) clock, or no matching policy
    row — deliberately not "healthy" in either case, since neither
    means the ticket is actually on track, just that there's nothing
    to classify yet.
    """

    remaining_seconds = func.extract("epoch", ResolutionSLA.due_at - now)
    target_seconds = SLAPolicy.resolution_target_minutes * 60

    return case(
        (ResolutionSLA.status != SLAClockStatus.RUNNING, None),
        (SLAPolicy.resolution_target_minutes.is_(None), None),
        (remaining_seconds <= target_seconds * -0.5, "escalated"),
        (remaining_seconds <= 0, "breached"),
        (remaining_seconds <= target_seconds * 0.2, "at_risk"),
        else_="healthy",
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

    def _escalated_exists_condition(self):
        """
        True when a ticket has a non-CLOSED TicketEscalation row — the
        "escalated" tab's filter, and (via count_by_view's own use of
        this as a FILTER clause) that tab's badge count. A correlated
        EXISTS rather than a JOIN here (list_all/count_by_view have no
        other reason to join `ticket_escalations`, unlike
        list_visible_page below, which already joins it for per-row
        display columns) — at most one non-CLOSED row per ticket is
        guaranteed by that table's own partial unique index, so this
        can never inflate a row count even if it were a join instead.
        """

        return exists().where(
            TicketEscalation.ticket_id == Ticket.ticket_id,
            TicketEscalation.status != EscalationStatus.CLOSED,
        )

    def _escalated_owner_condition(self, viewer_user_id: UUID):
        """
        True when a ticket has a non-CLOSED TicketEscalation row whose
        *current* `owner_ids` includes this specific viewer — the
        Escalated tab's real filter, as opposed to
        `_escalated_exists_condition` (any active escalation at any
        level, used for pool exclusion, where who currently owns it is
        irrelevant). Without this distinction, a ticket freshly
        escalated from Staff to Team Lead would also show up in every
        Account Manager's (and Site Lead's, and Super Admin's) queue
        immediately, just because they can otherwise see the ticket —
        even though the escalation hasn't reached their level yet. A
        Team Lead/Account Manager only ever appears in `owner_ids` once
        the chain actually reaches their level (see
        EscalationService._resolve_owners_for_level); Site Lead/Super
        Admin become owners automatically once it reaches SITE_LEAD
        (resolve_global_inbox_user_ids), so this same check naturally
        also keeps them out until then — no separate role-based
        bypass needed.
        """

        return exists().where(
            TicketEscalation.ticket_id == Ticket.ticket_id,
            TicketEscalation.status != EscalationStatus.CLOSED,
            TicketEscalation.owner_ids.contains([str(viewer_user_id)]),
        )

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
        viewer_user_id: UUID | None = None,
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
            # See list_visible_page's matching pool branch — an
            # unclaimed, escalated ticket is excluded here too, for the
            # same reason (it now has an owner via the escalation
            # chain), keeping this method's counts/results consistent
            # with that one's.
            conditions.append(not_(self._escalated_exists_condition()))
        elif view == "mine" and assigned_to is not None:
            conditions.append(Ticket.agent_id == assigned_to)
        elif view == "escalated":
            # Requires viewer_user_id to be a *current* owner of the
            # escalation, not just "this ticket is escalated at all" —
            # see _escalated_owner_condition's own docstring for why.
            conditions.append(
                self._escalated_owner_condition(viewer_user_id)
                if viewer_user_id is not None
                else self._escalated_exists_condition()
            )

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
        viewer_user_id: UUID | None = None,
    ) -> dict[str, int]:
        """
        One grouped query, three FILTERed counts — the ticket-list
        page's tab badges (Open Pool / My Tickets / All), under the
        exact same visibility scoping `list_visible_page` applies,
        without fetching a single ticket row. Same shape as
        InteractionRepository.count_by_view (the Mail page's own tab
        badges).

        The pool count excludes an escalated-but-unclaimed ticket, the
        same way `list_visible_page`'s own `view == "pool"` branch
        does (see that method's docstring: an escalated ticket now has
        an owner via the escalation chain, reached only through the
        Escalated tab, never auto-surfaced back into the general
        pool). This exclusion has to be applied here too, independent
        of that method — a stray pool count that includes what the
        pool *view* itself excludes is exactly the "badge says N, list
        shows fewer" staleness bug this was fixed to close.

        The escalated count is scoped to `viewer_user_id` being a
        *current* owner of the escalation (see
        `_escalated_owner_condition`) — same reasoning as
        `list_visible_page`'s own `view == "escalated"` branch, so this
        badge never shows a nonzero count for tickets whose escalation
        hasn't actually reached this viewer's level yet.
        """

        conditions = self._visibility_conditions(
            account_manager_id=account_manager_id, ticket_types=ticket_types
        )
        escalated_condition = (
            self._escalated_owner_condition(viewer_user_id)
            if viewer_user_id is not None
            else self._escalated_exists_condition()
        )

        query = select(
            func.count().filter(
                Ticket.agent_id.is_(None),
                Ticket.current_status == TicketStatus.OPEN,
                ~self._escalated_exists_condition(),
            ),
            func.count().filter(Ticket.agent_id == assigned_to),
            func.count(),
            func.count().filter(escalated_condition),
        ).where(*conditions)

        result = await self.db.execute(query)
        pool, mine, all_count, escalated = result.one()

        return {"pool": pool, "mine": mine, "all": all_count, "escalated": escalated}

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

    async def sla_overview_counts(
        self,
        *,
        account_manager_id: UUID | None,
        ticket_types: list[str] | None,
        now: datetime,
    ) -> dict[str, int]:
        """
        The Dashboard's "SLA Overview" tile row (Running / Paused / At
        Risk / Breached / Escalated / Completed) — one grouped query
        under the same visibility scoping as every other view here,
        replacing what useDashboardSlaCounts (frontend) used to do by
        fetching every visible ticket unbounded and then calling
        GET /tickets/{id}/sla once per ticket to classify it: an N+1
        round-trip pattern (1 + up to hundreds of individual SLA
        lookups) that was both why the tile was slow to resolve and why
        it sat on its loading placeholder for as long as it did.

        Mirrors compute_elapsed_fraction's exact formula (sla_service.py)
        entirely in SQL, expressed as a comparison of remaining seconds
        against the target rather than a division, so a zero-row/zero-
        target edge case never divides by zero: `remaining_seconds =
        EXTRACT(EPOCH FROM (due_at - now))`, and fraction thresholds
        become `remaining_seconds` compared against
        `target_seconds * (1 - threshold)`. Tickets whose priority has
        no matching (active) SLAPolicy row still count toward `running`
        (their clock is genuinely running) but toward none of the tier
        buckets — the NULL `target_seconds` makes every tier
        comparison evaluate to NULL/false, the same "can't classify
        without a target" outcome the old client-side loop had.

        `running`/`atRisk`/`breached`/`escalated` are deliberately not
        mutually exclusive — `running` is every RUNNING clock
        regardless of tier, and at_risk/breached/escalated are tier
        sub-classifications of that same set — this preserves the
        exact (if slightly unusual) counting semantics the previous
        client-side implementation already had, so the numbers
        strangers to this change would see don't shift underneath them.
        """

        conditions = self._visibility_conditions(
            account_manager_id=account_manager_id, ticket_types=ticket_types
        )

        remaining_seconds = func.extract(
            "epoch", ResolutionSLA.due_at - now
        )
        target_seconds = SLAPolicy.resolution_target_minutes * 60

        query = (
            select(
                func.count().filter(ResolutionSLA.status == SLAClockStatus.RUNNING),
                func.count().filter(ResolutionSLA.status == SLAClockStatus.PAUSED),
                func.count().filter(
                    ResolutionSLA.status == SLAClockStatus.RUNNING,
                    remaining_seconds > 0,
                    remaining_seconds <= target_seconds * 0.2,
                ),
                func.count().filter(
                    ResolutionSLA.status == SLAClockStatus.RUNNING,
                    remaining_seconds <= 0,
                    remaining_seconds > target_seconds * -0.5,
                ),
                func.count().filter(
                    ResolutionSLA.status == SLAClockStatus.RUNNING,
                    remaining_seconds <= target_seconds * -0.5,
                ),
                func.count().filter(ResolutionSLA.status == SLAClockStatus.COMPLETED),
            )
            .select_from(Ticket)
            .join(ResolutionSLA, ResolutionSLA.ticket_id == Ticket.ticket_id)
            .outerjoin(SLAPolicy, SLAPolicy.priority == ResolutionSLA.priority)
            .where(*conditions)
        )

        result = await self.db.execute(query)
        running, paused, at_risk, breached, escalated, completed = result.one()

        return {
            "running": running,
            "paused": paused,
            "at_risk": at_risk,
            "breached": breached,
            "escalated": escalated,
            "completed": completed,
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
        viewer_user_id: UUID | None = None,
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

        Also LEFT JOINs `ticket_escalations` (status != CLOSED — at
        most one such row per ticket, enforced by that table's own
        partial unique index, so this join can never fan a row out)
        for the `escalation_level`/`escalation_status`/
        `escalation_ack_due_at` display columns, and `resolution_slas`
        purely for `view == "mine"`'s own ordering below (its `due_at`
        is never selected as an output column here — TicketService
        already has a separate SLA-state endpoint for that).
        `view == "escalated"` requires the escalation join to have
        actually matched (`escalation_id IS NOT NULL`) — the tab's own
        filter. `view == "mine"` gets a fixed, escalation-aware
        ordering instead of the plain `sort_by`/`sort_dir` column: 1)
        actively escalated tickets, 2) HIGH-priority tickets, 3)
        nearest Resolution SLA deadline, 4) the caller's own chosen
        sort column/direction, 5) `ticket_id` as a final, deterministic
        tie-breaker. `view == "pool"` gets its own fixed ordering too —
        strictly by Resolution SLA tier (Escalated -> Breached -> At
        Risk -> Healthy/unknown), then HIGH-priority, then nearest due
        date, then the caller's chosen sort, then `ticket_id` — a
        deliberately different shape from `mine`'s (tier-first rather
        than escalation-flag-first), since surfacing at-risk pool
        tickets to whoever might claim them is the point of this view.
        Every other view keeps the plain column sort unchanged. Also
        LEFT JOINs `sla_policies` (on priority) so every row can carry
        a `resolution_sla_tier` output column (the same tier used for
        `pool`'s own ordering) regardless of view.
        """

        now = datetime.now(timezone.utc)

        conditions = self._visibility_conditions(
            account_manager_id=account_manager_id, ticket_types=ticket_types
        )

        if view == "pool":
            conditions.append(Ticket.agent_id.is_(None))
            conditions.append(Ticket.current_status == TicketStatus.OPEN)
            # An unclaimed ticket that's escalated is excluded here,
            # never auto-assigned — it now has an owner via the
            # escalation chain (Team Lead/Manager/Site Lead), exactly
            # mirroring how an already-claimed escalated ticket is
            # already invisible in this view (agent_id is set). Reaches
            # whoever's meant to act on it only through the Escalated
            # tab's own Acknowledge & Assign flow.
            conditions.append(TicketEscalation.escalation_id.is_(None))
        elif view == "mine" and assigned_to is not None:
            conditions.append(Ticket.agent_id == assigned_to)
        elif view == "escalated":
            # Requires viewer_user_id to be a *current* owner of the
            # escalation (owner_ids), not just "this ticket has an
            # active escalation at any level" — otherwise a ticket
            # freshly escalated from Staff to Team Lead would also show
            # up in every Account Manager's/Site Lead's/Super Admin's
            # queue immediately, since they could already see the
            # ticket via ordinary visibility scoping. See
            # TicketRepository._escalated_owner_condition's docstring.
            conditions.append(
                TicketEscalation.owner_ids.contains([str(viewer_user_id)])
                if viewer_user_id is not None
                else TicketEscalation.escalation_id.isnot(None)
            )

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
        chosen_order = sort_column.asc() if sort_dir == "asc" else sort_column.desc()

        resolution_sla_tier = _resolution_sla_tier_case(now)

        if view == "mine":
            order_clauses = (
                case((TicketEscalation.escalation_id.isnot(None), 0), else_=1).asc(),
                case((Ticket.current_priority == TicketPriority.HIGH, 0), else_=1).asc(),
                ResolutionSLA.due_at.asc().nullslast(),
                chosen_order,
                Ticket.ticket_id.asc(),
            )
        elif view == "pool":
            tier_rank = case(
                (resolution_sla_tier == "escalated", 0),
                (resolution_sla_tier == "breached", 1),
                (resolution_sla_tier == "at_risk", 2),
                (resolution_sla_tier == "healthy", 3),
                else_=4,
            )
            order_clauses = (
                tier_rank.asc(),
                case((Ticket.current_priority == TicketPriority.HIGH, 0), else_=1).asc(),
                ResolutionSLA.due_at.asc().nullslast(),
                chosen_order,
                Ticket.ticket_id.asc(),
            )
        else:
            order_clauses = (chosen_order,)

        ClientUser = aliased(User)
        AgentUser = aliased(User)
        CreatedByUser = aliased(User)

        # Per-viewer, not per-ticket — whether *this specific caller*
        # is a current owner of the ticket's escalation, so the
        # frontend can gate the Acknowledge/Assign action without
        # offering a button that would 403 (e.g. an Account Manager
        # browsing the unrestricted "All" tab, viewing a ticket only
        # escalated to Team Lead so far). See TicketResponse.
        # is_escalation_owner's own docstring.
        is_escalation_owner_expr = (
            func.coalesce(
                TicketEscalation.owner_ids.contains([str(viewer_user_id)]), False
            )
            if viewer_user_id is not None
            else literal(False)
        )

        def _base_select(*extra_columns):
            return (
                select(
                    Ticket,
                    ClientUser.name.label("client_name"),
                    Client.name.label("client_company_name"),
                    AgentUser.name.label("agent_name"),
                    CreatedByUser.name.label("created_by_name"),
                    TicketEscalation.level.label("escalation_level"),
                    TicketEscalation.status.label("escalation_status"),
                    TicketEscalation.ack_due_at.label("escalation_ack_due_at"),
                    is_escalation_owner_expr.label("is_escalation_owner"),
                    resolution_sla_tier.label("resolution_sla_tier"),
                    *extra_columns,
                )
                .outerjoin(ClientUser, ClientUser.user_id == Ticket.client_id)
                .outerjoin(Client, Client.client_id == Ticket.client_company_id)
                .outerjoin(AgentUser, AgentUser.user_id == Ticket.agent_id)
                .outerjoin(CreatedByUser, CreatedByUser.user_id == Ticket.created_by)
                .outerjoin(
                    TicketEscalation,
                    and_(
                        TicketEscalation.ticket_id == Ticket.ticket_id,
                        TicketEscalation.status != EscalationStatus.CLOSED,
                    ),
                )
                .outerjoin(ResolutionSLA, ResolutionSLA.ticket_id == Ticket.ticket_id)
                .outerjoin(SLAPolicy, SLAPolicy.priority == ResolutionSLA.priority)
                .where(*conditions)
            )

        page_query = (
            _base_select(func.count().over().label("full_count"))
            .order_by(*order_clauses)
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(page_query)
        rows = result.all()

        if rows:
            return TicketVisiblePage(items=rows, total=rows[0].full_count)

        # Explicitly (outer-)joins TicketEscalation here too — the
        # `view == "escalated"` condition above references it, and a
        # WHERE-only reference to a table absent from FROM is exactly
        # the kind of implicit-cross-join footgun this codebase avoids
        # everywhere else; ResolutionSLA is omitted since this fallback
        # only ever computes a count, never orders anything.
        count_result = await self.db.execute(
            select(func.count())
            .select_from(Ticket)
            .outerjoin(
                TicketEscalation,
                and_(
                    TicketEscalation.ticket_id == Ticket.ticket_id,
                    TicketEscalation.status != EscalationStatus.CLOSED,
                ),
            )
            .where(*conditions)
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
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from shared_models.models import User

from app.core.request_timing import timed_stage
from app.ticketing.enums import InteractionDirection, InteractionStatus, TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.ticket import Ticket
from app.ticketing.schemas.interaction import (
    InteractionCreate,
    InteractionUpdate,
)


class InteractionVisiblePage:
    """
    Plain result holder for list_visible_page — a page of interactions
    already joined against Ticket/Client/User so the caller never needs
    a separate enrichment round trip. `total` is the full filtered
    count (every page, not just this one), same meaning `total` has
    always had on this endpoint.
    """

    __slots__ = ("items", "total")

    def __init__(self, items, total: int):
        self.items = items
        self.total = total


class InteractionRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        data: InteractionCreate,
    ) -> Interaction:

        interaction = Interaction(**data.model_dump())

        self.db.add(interaction)

        await self.db.flush()

        await self.db.refresh(interaction)

        return interaction

    async def get_by_id(
        self,
        interaction_id: UUID,
    ) -> Interaction | None:

        result = await self.db.execute(

            select(Interaction).where(
                Interaction.interaction_id == interaction_id
            )

        )

        return result.scalar_one_or_none()

    async def list_by_ticket_id(
        self,
        ticket_id: UUID,
    ) -> list[Interaction]:

        result = await self.db.execute(

            select(Interaction)
            .where(
                Interaction.ticket_id == ticket_id
            )
            .order_by(
                Interaction.created_at.asc()
            )

        )

        return list(result.scalars().all())

    async def list_by_ticket_ids(
        self,
        ticket_ids: list[UUID],
        *,
        limit: int | None = None,
        offset: int = 0,
        cursor: tuple[datetime, UUID] | None = None,
        interaction_type: str | None = None,
        interaction_types: list[str] | None = None,
        direction: InteractionDirection | None = None,
        status: InteractionStatus | None = None,
        performed_by: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
    ) -> tuple[list[Interaction], int]:
        """
        Same shape as list_by_ticket_id, batched over many tickets at
        once — lets a page that needs every visible ticket's timeline
        (the Interactions page) run one query instead of one request
        per ticket.

        `limit=None` (the default) preserves this method's original,
        unbounded behavior — every matching row, ordered ascending,
        with `total` just `len(items)` (no separate COUNT needed).
        Passing `limit` switches to a real bounded, filtered query
        (newest first, matching how the Interactions page displays
        results) plus a COUNT(*) over the same filters so the caller
        can report an accurate total against the *filtered* set, not
        just the page in hand. `search` only matches `subject` (the
        real, populated column for every row this page actually shows
        — see Interaction.subject's own docstring) — it does not reach
        into `payload` or join out to the owning ticket's title/client
        name, unlike this page's older client-side-only search.

        `interaction_types` (a fixed baseline set) and `interaction_type`
        (one further, optional single-value narrowing) can both be
        given at once — see TicketService.list_all_interactions, which
        always passes the former in paginated mode to reproduce the
        Interactions page's permanent EMAIL/REPLY/INTERNAL_NOTE
        whitelist server-side.

        `cursor`, when given alongside `limit`, switches from OFFSET
        paging to keyset paging: instead of skipping `offset` rows
        (cost grows with depth, however good the index), it fetches
        rows strictly older than `(created_at, interaction_id)` —
        cost stays O(limit) regardless of how deep the page is. Additive
        and opt-in only: `offset` is ignored when `cursor` is provided,
        and every existing offset-based caller is unaffected. `total`
        is still computed the same way either way, for response-shape
        parity with the offset mode.
        """

        if not ticket_ids:
            return [], 0

        conditions = [Interaction.ticket_id.in_(ticket_ids)]

        if interaction_types is not None:
            conditions.append(Interaction.interaction_type.in_(interaction_types))
        if interaction_type is not None:
            conditions.append(Interaction.interaction_type == interaction_type)
        if direction is not None:
            conditions.append(Interaction.direction == direction)
        if status is not None:
            conditions.append(Interaction.status == status)
        if performed_by is not None:
            conditions.append(Interaction.performed_by == performed_by)
        if date_from is not None:
            conditions.append(Interaction.created_at >= date_from)
        if date_to is not None:
            conditions.append(Interaction.created_at <= date_to)
        if search:
            conditions.append(Interaction.subject.ilike(f"%{search}%"))

        if limit is None:
            result = await self.db.execute(
                select(Interaction).where(*conditions).order_by(Interaction.created_at.asc())
            )
            items = list(result.scalars().all())
            return items, len(items)

        with timed_stage("count"):
            count_result = await self.db.execute(
                select(func.count()).select_from(Interaction).where(*conditions)
            )
            total = count_result.scalar_one()

        page_conditions = list(conditions)
        if cursor is not None:
            cursor_created_at, cursor_id = cursor
            page_conditions.append(
                tuple_(Interaction.created_at, Interaction.interaction_id)
                < tuple_(cursor_created_at, cursor_id)
            )

        query = (
            select(Interaction)
            .where(*page_conditions)
            .order_by(Interaction.created_at.desc(), Interaction.interaction_id.desc())
            .limit(limit)
        )
        if cursor is None:
            query = query.offset(offset)

        with timed_stage("query"):
            result = await self.db.execute(query)
            items = list(result.scalars().all())

        return items, total

    async def list_visible_page(
        self,
        *,
        account_manager_id: UUID | None,
        ticket_types: list[str] | None,
        ticket_id: UUID | None = None,
        limit: int,
        offset: int = 0,
        cursor: tuple[datetime, UUID] | None = None,
        interaction_type: str | None = None,
        interaction_types: list[str] | None = None,
        direction: InteractionDirection | None = None,
        status: InteractionStatus | None = None,
        performed_by: UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        search: str | None = None,
    ) -> InteractionVisiblePage:
        """
        The Interactions-tab query, collapsed into as few round trips
        as the DB round-trip-latency investigation in this session
        found practical (see request_timing.py / Server-Timing) — one
        query normally, occasionally two (see the empty-page fallback
        below), replacing what used to be 5 separate round trips
        (visible-ticket list, name-enrichment union, count, page
        query, performer-name enrichment):

        - Visibility is enforced by JOINing to `tickets` and filtering
          there directly, instead of first fetching every visible
          ticket's id into a Python list and then filtering
          interactions by `ticket_id IN (...)`. `account_manager_id`
          (only set for the Account Manager role) is applied as an
          `IN (SELECT client_id FROM clients WHERE
          account_manager_id = ...)` subquery in the SAME statement,
          instead of a separate round trip to resolve owned client ids
          first — an Account Manager who owns zero clients still
          "sees nothing" for free, since `IN (empty set)` naturally
          matches no rows, with no special-case needed.
          `ticket_types` (Team Lead/Staff category scoping) costs
          nothing extra either way — it was already resolved with no
          DB call, from `current_user.category`, which
          `UserRepository.get_by_id` eager-loads at auth time.
        - `ticket_title`/`client_company_name`/`performed_by_name` are
          resolved via LEFT/INNER JOINs directly in this query instead
          of a separate name-lookup round trip afterward — every
          field the Interactions list actually displays comes back on
          the same row as the interaction itself. Only many-to-one
          joins are used here (a ticket has one title, one client
          company, an interaction has one performer) — nothing here
          can multiply/duplicate a row the way a one-to-many join
          (attachments, replies) would, which is why those are
          deliberately NOT joined in; see get_thread for where
          attachments/full threads are actually fetched, only once a
          row is clicked.
        - `total` comes from `COUNT(*) OVER()` (a window function) —
          computed by Postgres over every row matching the WHERE
          clause *before* LIMIT/OFFSET trims the result down to one
          page, so it reports the same "total across every page"
          value the old separate COUNT(*) query did, in the same
          statement as the page itself. This does NOT work when
          `cursor` is given: a keyset predicate
          (`(created_at, id) < cursor`) is itself part of the WHERE
          clause the window function sees, so it would report "total
          remaining after this cursor," not the grand total across
          every page — a real semantic difference from the offset
          mode's `total`, not just a performance one. Since the
          current frontend caller only ever uses `offset` (`cursor`
          is an additive, not-yet-used-by-any-caller keyset-paging
          option — see list_by_ticket_ids' own docstring), `cursor`
          mode intentionally falls back to the original two-round-trip
          count-then-page shape here rather than risk a wrong total
          on a path nothing exercises yet.
        - The window function also can't produce a value when zero
          rows match (there's nothing to attach it to) — covers both
          a genuinely empty filtered set and an `offset` past the end
          of a non-empty one. That's the one case a second round trip
          (a plain `COUNT(*)`, same filters, no limit/offset/window)
          still happens — deliberately, since "how many matches exist"
          can't be answered by a query that returned no rows to carry
          the answer on. It never fires on the common non-empty-page
          path.
        """

        Performer = aliased(User)

        conditions = [Interaction.ticket_id.isnot(None)]

        if account_manager_id is not None:
            owned_client_ids = select(Client.client_id).where(
                Client.account_manager_id == account_manager_id
            )
            conditions.append(Ticket.client_company_id.in_(owned_client_ids))

        if ticket_types is not None:
            conditions.append(Ticket.ticket_type.in_(ticket_types))

        if ticket_id is not None:
            conditions.append(Ticket.ticket_id == ticket_id)

        if interaction_types is not None:
            conditions.append(Interaction.interaction_type.in_(interaction_types))
        if interaction_type is not None:
            conditions.append(Interaction.interaction_type == interaction_type)
        if direction is not None:
            conditions.append(Interaction.direction == direction)
        if status is not None:
            conditions.append(Interaction.status == status)
        if performed_by is not None:
            conditions.append(Interaction.performed_by == performed_by)
        if date_from is not None:
            conditions.append(Interaction.created_at >= date_from)
        if date_to is not None:
            conditions.append(Interaction.created_at <= date_to)
        if search:
            conditions.append(Interaction.subject.ilike(f"%{search}%"))

        def _base_select(*extra_columns):
            return (
                select(
                    Interaction,
                    Ticket.title.label("ticket_title"),
                    Client.name.label("client_company_name"),
                    Performer.name.label("performed_by_name"),
                    *extra_columns,
                )
                .join(Ticket, Ticket.ticket_id == Interaction.ticket_id)
                .outerjoin(Client, Client.client_id == Ticket.client_company_id)
                .outerjoin(Performer, Performer.user_id == Interaction.performed_by)
                .where(*conditions)
            )

        if cursor is not None:
            # Deep-paging opt-in mode — see docstring above for why
            # this keeps the original separate-count shape rather than
            # the window-function one.
            with timed_stage("count"):
                count_result = await self.db.execute(
                    select(func.count())
                    .select_from(Interaction)
                    .join(Ticket, Ticket.ticket_id == Interaction.ticket_id)
                    .where(*conditions)
                )
                total = count_result.scalar_one()

            cursor_created_at, cursor_id = cursor
            page_query = (
                _base_select()
                .where(
                    tuple_(Interaction.created_at, Interaction.interaction_id)
                    < tuple_(cursor_created_at, cursor_id)
                )
                .order_by(Interaction.created_at.desc(), Interaction.interaction_id.desc())
                .limit(limit)
            )
            with timed_stage("query"):
                result = await self.db.execute(page_query)
                items = result.all()

            return InteractionVisiblePage(items=items, total=total)

        page_query = (
            _base_select(func.count().over().label("full_count"))
            .order_by(Interaction.created_at.desc(), Interaction.interaction_id.desc())
            .limit(limit)
            .offset(offset)
        )

        with timed_stage("query"):
            result = await self.db.execute(page_query)
            rows = result.all()

        if rows:
            return InteractionVisiblePage(items=rows, total=rows[0].full_count)

        # Empty page — the window function had no row to report a
        # total on. One fallback COUNT(*), same filters, no
        # limit/offset/window — only reached here, never on the
        # normal non-empty path above.
        with timed_stage("count"):
            count_result = await self.db.execute(
                select(func.count())
                .select_from(Interaction)
                .join(Ticket, Ticket.ticket_id == Interaction.ticket_id)
                .where(*conditions)
            )
            total = count_result.scalar_one()

        return InteractionVisiblePage(items=[], total=total)

    async def list_inbox(
        self,
        account_manager_id: UUID | None = None,
        client_id: UUID | None = None,
        view: str = "pending",
        folder_id: UUID | None = None,
        ticket_type: str | None = None,
        assigned_agent_id: UUID | None = None,
        extra_ticket_ids: list[UUID] | None = None,
        *,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        cursor: tuple[datetime, UUID] | None = None,
        category_filter: str | None = None,
        priority_filter: TicketPriority | None = None,
    ) -> tuple[list[Interaction], int]:
        """
        The role-scoped inbox query — always over thread ROOTS
        (parent_interaction_id IS NULL, interaction_type == "EMAIL");
        replies are fetched separately via `list_thread` once a root
        is opened.

        - `account_manager_id` set: only mail belonging to clients
          that AM owns (a join against `clients`). None (and
          `ticket_type`/`assigned_agent_id` also None) means "every
          client" — the Site Lead/Super Admin global inbox.
        - `client_id` set: further narrows to one client (the
          per-client filter on the inbox UI).
        - `folder_id` set: further narrows to one custom folder —
          orthogonal to `view` (a folder can hold items in any
          status), so this composes with any of the views below
          rather than being its own view.
        - `ticket_type` set: Team Lead scoping — only threads whose
          ticket is filed under this work-specialization category.
          Implemented as an INNER join against `tickets`, so this
          also implicitly restricts to ticketed threads only (a
          Team Lead never sees a still-pending, pre-ticket item —
          see the role propagation rules in InboxService.get_inbox).
        - `assigned_agent_id` set: Staff scoping — only threads whose
          ticket is currently assigned to (claimed by) this agent, or
          (if `extra_ticket_ids` is also given) one this Staff member
          holds an approved edit-access grant on — otherwise an
          approved request never surfaces the ticket's mail thread in
          Staff's own inbox, only reachable via the Tickets page.
          Same inner-join-implies-ticketed-only reasoning as above.
        - `view`:
          - "pending": not yet replied to or ticketed — the triage
            queue.
          - "replied": answered directly, never became a ticket.
          - "ticketed": promoted to (or attached onto) a ticket.
          - "archived": marked Informational/Archive — stored, no
            ticket, no work assignment, still searchable here.
          - "all": every root email regardless of state — the "All
            Inboxes" overview, normally paired with no account_manager
            scoping.

        `limit=None` (the default) preserves this method's original
        unbounded behavior, with `total` just `len(items)` — no
        separate COUNT query. Passing `limit` runs a COUNT(*) over the
        same filters first (so `total` reflects the full filtered set,
        not just the page in hand), then applies `ORDER BY ...
        LIMIT/OFFSET` for the actual page. `search` matches `subject`
        only (the same narrowing as list_by_ticket_ids — see that
        method's docstring). `cursor` is the same additive, opt-in
        keyset-pagination mode as list_by_ticket_ids — see that
        method's docstring — keyed on `(received_at, interaction_id)`
        here instead of `(created_at, interaction_id)`, since that's
        this query's own sort column.

        `category_filter`/`priority_filter` are the user-facing Mail
        UI filters (distinct from `ticket_type`, which is Team Lead's
        own fixed role scoping) — previously applied client-side over
        whatever page happened to be loaded, which meant "show me
        every HIGH-priority thread" could silently miss matches
        outside the currently-fetched batch. Both only ever match
        ticketed threads (priority/category don't exist before a
        thread becomes a ticket), so either one triggers the same
        INNER JOIN against `tickets` already used for
        `ticket_type`/`assigned_agent_id` scoping.
        """

        query = select(Interaction)

        if account_manager_id is not None or client_id is not None:
            query = query.join(Client, Client.client_id == Interaction.client_id)

        if account_manager_id is not None:
            query = query.where(Client.account_manager_id == account_manager_id)

        if client_id is not None:
            query = query.where(Interaction.client_id == client_id)

        needs_ticket_join = (
            ticket_type is not None
            or assigned_agent_id is not None
            or category_filter is not None
            or priority_filter is not None
        )
        if needs_ticket_join:
            query = query.join(Ticket, Ticket.ticket_id == Interaction.ticket_id)

        if ticket_type is not None:
            query = query.where(Ticket.ticket_type == ticket_type)

        if assigned_agent_id is not None:
            if extra_ticket_ids:
                query = query.where(
                    or_(
                        Ticket.agent_id == assigned_agent_id,
                        Ticket.ticket_id.in_(extra_ticket_ids),
                    )
                )
            else:
                query = query.where(Ticket.agent_id == assigned_agent_id)

        if category_filter is not None:
            query = query.where(Ticket.ticket_type == category_filter)

        if priority_filter is not None:
            query = query.where(Ticket.current_priority == priority_filter)

        if folder_id is not None:
            query = query.where(Interaction.folder_id == folder_id)

        query = query.where(
            Interaction.is_visible.is_(True),
            Interaction.interaction_type == "EMAIL",
            Interaction.parent_interaction_id.is_(None),
        )

        if view == "pending":
            query = query.where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
            )
        elif view == "replied":
            query = query.where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.ASSIGNED,
            )
        elif view == "ticketed":
            query = query.where(Interaction.ticket_id.isnot(None))
        elif view == "archived":
            query = query.where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.IGNORED,
            )
        # view == "all": no further filter — every root email.

        if search:
            query = query.where(Interaction.subject.ilike(f"%{search}%"))

        if limit is None:
            query = query.order_by(Interaction.received_at.desc())
            result = await self.db.execute(query)
            items = list(result.scalars().all())
            return items, len(items)

        count_result = await self.db.execute(
            select(func.count()).select_from(query.subquery())
        )
        total = count_result.scalar_one()

        page_query = query.order_by(
            Interaction.received_at.desc(), Interaction.interaction_id.desc()
        ).limit(limit)

        if cursor is not None:
            cursor_received_at, cursor_id = cursor
            page_query = page_query.where(
                tuple_(Interaction.received_at, Interaction.interaction_id)
                < tuple_(cursor_received_at, cursor_id)
            )
        else:
            page_query = page_query.offset(offset)

        result = await self.db.execute(page_query)

        return list(result.scalars().all()), total

    async def count_by_folder(
        self,
        account_manager_id: UUID | None = None,
        client_id: UUID | None = None,
        ticket_type: str | None = None,
        assigned_agent_id: UUID | None = None,
        extra_ticket_ids: list[UUID] | None = None,
    ) -> dict[UUID, int]:
        """
        One grouped COUNT per custom folder, under the exact same
        role-scoping `list_inbox` applies for `view="all"` — backs
        the Mail sidebar's per-folder badges without the N full
        list-and-serialize round trips (one per folder) that used to
        require.
        """

        query = select(Interaction.folder_id, func.count(Interaction.interaction_id))

        if account_manager_id is not None or client_id is not None:
            query = query.join(Client, Client.client_id == Interaction.client_id)

        if account_manager_id is not None:
            query = query.where(Client.account_manager_id == account_manager_id)

        if client_id is not None:
            query = query.where(Interaction.client_id == client_id)

        if ticket_type is not None or assigned_agent_id is not None:
            query = query.join(Ticket, Ticket.ticket_id == Interaction.ticket_id)

        if ticket_type is not None:
            query = query.where(Ticket.ticket_type == ticket_type)

        if assigned_agent_id is not None:
            if extra_ticket_ids:
                query = query.where(
                    or_(
                        Ticket.agent_id == assigned_agent_id,
                        Ticket.ticket_id.in_(extra_ticket_ids),
                    )
                )
            else:
                query = query.where(Ticket.agent_id == assigned_agent_id)

        query = query.where(
            Interaction.is_visible.is_(True),
            Interaction.interaction_type == "EMAIL",
            Interaction.parent_interaction_id.is_(None),
            Interaction.folder_id.isnot(None),
        ).group_by(Interaction.folder_id)

        result = await self.db.execute(query)

        return {folder_id: count for folder_id, count in result.all()}

    async def count_by_view(
        self,
        account_manager_id: UUID | None = None,
        client_id: UUID | None = None,
        ticket_type: str | None = None,
        assigned_agent_id: UUID | None = None,
        extra_ticket_ids: list[UUID] | None = None,
    ) -> dict[str, int]:
        """
        One query, five conditional counts (Postgres FILTER) — the
        Mail sidebar's view badges (Pending/Replied/Ticketed/Archived/
        All) under the same role scoping as list_inbox, without
        fetching a single row of actual mail. Row *data* per view is
        now fetched lazily (only once a tab is actually opened); this
        keeps the badge counts accurate regardless of which tabs have
        been visited yet.
        """

        query = select(
            func.count().filter(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
            ),
            func.count().filter(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.ASSIGNED,
            ),
            func.count().filter(Interaction.ticket_id.isnot(None)),
            func.count().filter(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.IGNORED,
            ),
            func.count(),
        )

        if account_manager_id is not None or client_id is not None:
            query = query.join(Client, Client.client_id == Interaction.client_id)

        if account_manager_id is not None:
            query = query.where(Client.account_manager_id == account_manager_id)

        if client_id is not None:
            query = query.where(Interaction.client_id == client_id)

        if ticket_type is not None or assigned_agent_id is not None:
            query = query.join(Ticket, Ticket.ticket_id == Interaction.ticket_id)

        if ticket_type is not None:
            query = query.where(Ticket.ticket_type == ticket_type)

        if assigned_agent_id is not None:
            if extra_ticket_ids:
                query = query.where(
                    or_(
                        Ticket.agent_id == assigned_agent_id,
                        Ticket.ticket_id.in_(extra_ticket_ids),
                    )
                )
            else:
                query = query.where(Ticket.agent_id == assigned_agent_id)

        query = query.where(
            Interaction.is_visible.is_(True),
            Interaction.interaction_type == "EMAIL",
            Interaction.parent_interaction_id.is_(None),
        )

        result = await self.db.execute(query)
        pending, replied, ticketed, archived, all_count = result.one()

        return {
            "pending": pending,
            "replied": replied,
            "ticketed": ticketed,
            "archived": archived,
            "all": all_count,
        }

    async def list_thread(
        self,
        root_interaction_id: UUID,
    ) -> list[Interaction]:
        """
        Every reply/follow-up filed under a thread root, at any
        nesting depth, oldest first — the conversation shown under an
        inbox email.

        A recursive CTE, not a single `parent_interaction_id ==
        root_interaction_id` filter — the write path (see
        email_service.py's inbound-threading match) always flattens a
        new reply's parent to point directly at the thread root, so in
        today's data this recurses exactly once and returns the same
        rows a flat filter would. But that flattening is an invariant
        enforced by application code, not the schema — nothing stops
        a future write path (or a manual data fix) from creating a
        real multi-level chain (root -> reply -> reply-to-that-reply),
        and a flat filter would then silently drop every reply past
        the first level with no error. This is correct at any depth,
        using only the indexed `parent_interaction_id` column at each
        step — not a full-table scan.
        """

        base = (
            select(Interaction)
            .where(
                Interaction.parent_interaction_id == root_interaction_id,
                Interaction.is_visible.is_(True),
            )
            .cte(name="thread_descendants", recursive=True)
        )
        child = aliased(Interaction)
        base = base.union_all(
            select(child).where(
                child.parent_interaction_id == base.c.interaction_id,
                child.is_visible.is_(True),
            )
        )
        thread_entity = aliased(Interaction, base)

        result = await self.db.execute(
            select(thread_entity).order_by(thread_entity.created_at.asc())
        )

        return list(result.scalars().all())

    async def find_thread_root(self, interaction_id: UUID) -> Interaction | None:
        """
        Walks up `parent_interaction_id` from any interaction — the
        thread root itself, a direct reply, or a deeply nested
        descendant — to the true root, via one recursive CTE. Correct
        regardless of nesting depth, unlike a single `parent
        _interaction_id or self` hop (which only resolves exactly one
        level and silently returns the wrong "root" for anything
        nested deeper) — see list_thread's own docstring for why this
        matters even though today's write path keeps every thread
        flat. Returns None if `interaction_id` doesn't exist.
        """

        base = (
            select(Interaction)
            .where(Interaction.interaction_id == interaction_id)
            .cte(name="thread_ancestors", recursive=True)
        )
        parent = aliased(Interaction)
        base = base.union_all(
            select(parent).where(parent.interaction_id == base.c.parent_interaction_id)
        )
        ancestor_entity = aliased(Interaction, base)

        result = await self.db.execute(
            select(ancestor_entity)
            .where(ancestor_entity.parent_interaction_id.is_(None))
            .limit(1)
        )
        root = result.scalar_one_or_none()
        if root is not None:
            return root

        # No ancestor with parent_interaction_id IS NULL was found —
        # either interaction_id doesn't exist, or (defensively) every
        # ancestor found so far still has a parent, which would only
        # happen on a genuinely malformed/cyclic chain. Fall back to
        # the interaction itself if it exists, so a real row is never
        # mistaken for "not found" just because its chain doesn't
        # terminate cleanly.
        return await self.get_by_id(interaction_id)

    async def list_sent(
        self,
        performed_by: UUID,
    ) -> list[Interaction]:
        """
        Every reply the given user has sent — pre-ticket or
        ticket-level alike, both created via the same REPLY/OUTBOUND
        shape (see `InteractionService.add_interaction_reply`/
        `add_reply`) — plus every brand-new Compose email they've
        authored (InteractionService.compose_email), which is itself
        a thread ROOT rather than a child. A sent reply's subject/
        client is resolved by the caller via `list_by_ids` on
        `parent_interaction_id`; a sent Compose root already carries
        its own subject/client on its own payload (see
        InboxService.get_sent's branch on `parent_interaction_id is
        None`).
        """

        result = await self.db.execute(
            select(Interaction)
            .where(
                or_(
                    Interaction.interaction_type == "REPLY",
                    and_(
                        Interaction.interaction_type == "EMAIL",
                        Interaction.parent_interaction_id.is_(None),
                    ),
                ),
                Interaction.direction == InteractionDirection.OUTBOUND,
                Interaction.performed_by == performed_by,
                Interaction.is_visible.is_(True),
            )
            .order_by(Interaction.created_at.desc())
        )

        return list(result.scalars().all())

    async def list_inbound_emails_for_client(
        self,
        client_id: UUID,
    ) -> list[Interaction]:
        """
        Every inbound EMAIL interaction ever received from this
        client company, most recent first — the raw material for
        deriving "every personal address this client has contacted
        our shared inbox from" (see ClientService.list_contacts).
        Deduping by from_email is left to the caller since that's a
        display concern, not a query one.
        """

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.client_id == client_id,
                Interaction.interaction_type == "EMAIL",
                Interaction.direction == InteractionDirection.INBOUND,
                Interaction.is_visible.is_(True),
            )
            .order_by(Interaction.received_at.desc())
        )

        return list(result.scalars().all())

    async def list_by_ids(
        self,
        interaction_ids: list[UUID],
    ) -> list[Interaction]:
        """Batch fetch — used to resolve a set of thread roots in one query."""

        if not interaction_ids:
            return []

        result = await self.db.execute(
            select(Interaction).where(Interaction.interaction_id.in_(interaction_ids))
        )

        return list(result.scalars().all())

    async def get_draft(
        self,
        root_interaction_id: UUID,
        performed_by: UUID,
    ) -> Interaction | None:
        """
        The given agent's active draft on this thread, if any. Meant to
        be at most one row — enforced at the database level by
        ix_interactions_one_draft_per_thread_per_agent — but reads the
        most recently created one via ORDER BY + LIMIT 1 rather than
        scalar_one_or_none(), so a request against a pre-existing
        duplicate (created before that constraint existed, or any
        future violation this doesn't anticipate) degrades to "return
        the newest" instead of a 500.
        """

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.parent_interaction_id == root_interaction_id,
                Interaction.performed_by == performed_by,
                Interaction.is_draft.is_(True),
                Interaction.is_visible.is_(True),
            )
            .order_by(Interaction.created_at.desc())
            .limit(1)
        )

        return result.scalars().first()

    async def update_draft_message(
        self,
        interaction: Interaction,
        message: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> Interaction:
        """Overwrites a draft's saved text (and Cc/Bcc) in place — upsert's "update" half."""

        interaction.payload = {
            **interaction.payload,
            "message": message,
            "cc": cc if cc is not None else interaction.payload.get("cc", []),
            "bcc": bcc if bcc is not None else interaction.payload.get("bcc", []),
        }

        await self.db.flush()
        await self.db.refresh(interaction)

        return interaction

    async def delete_draft(
        self,
        interaction: Interaction,
    ) -> None:
        """
        Hard-deletes a draft row. Unlike every other Interaction (soft-
        deleted via `hide`), a draft was never visible communication —
        nothing on the timeline/audit trail ever references it, so
        there's nothing a soft-delete would need to preserve.
        """

        await self.db.delete(interaction)
        await self.db.flush()

    async def list_drafts(
        self,
        performed_by: UUID,
    ) -> list[Interaction]:
        """Every draft the given agent currently has saved, across every thread."""

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.is_draft.is_(True),
                Interaction.performed_by == performed_by,
                Interaction.is_visible.is_(True),
            )
            .order_by(Interaction.created_at.desc())
        )

        return list(result.scalars().all())

    async def get_by_message_ids(
        self,
        message_ids: list[str],
    ) -> list[Interaction]:
        """
        Looks up interactions by their message_id — the thread-match
        step: an inbound email's In-Reply-To/References are checked
        against message_ids we've already stored (ours or the
        client's) to decide whether it's a new conversation or a
        continuation of one.
        """

        if not message_ids:
            return []

        result = await self.db.execute(
            select(Interaction).where(Interaction.message_id.in_(message_ids))
        )

        return list(result.scalars().all())

    async def get_by_conversation_id(
        self,
        conversation_id: str,
    ) -> list[Interaction]:
        """
        Looks up interactions by Graph's conversation_id — the
        highest-priority thread-match signal once Task 1 ships real
        Graph data (unused by the dummy-mail flow today, since
        nothing populates conversation_id yet).
        """

        result = await self.db.execute(
            select(Interaction).where(Interaction.conversation_id == conversation_id)
        )

        return list(result.scalars().all())

    async def list_thread_summaries(
        self,
        root_interaction_ids: list[UUID],
    ) -> dict[UUID, tuple[int, Interaction | None]]:
        """
        Batched "how many replies, and what's the latest one" lookup
        for a set of thread roots — used to populate the inbox list's
        reply_count/latest_* columns without an N+1 query per row.
        Returns {root_id: (reply_count, latest_reply_or_None)}; a
        root with zero replies is simply absent from the dict.
        """

        if not root_interaction_ids:
            return {}

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.parent_interaction_id.in_(root_interaction_ids),
                Interaction.is_visible.is_(True),
                Interaction.is_draft.is_(False),
            )
            .order_by(Interaction.created_at.asc())
        )

        summaries: dict[UUID, tuple[int, Interaction | None]] = {}
        for reply in result.scalars().all():
            root_id = reply.parent_interaction_id
            count, _latest = summaries.get(root_id, (0, None))
            # Rows arrive oldest-first, so the last one seen per root
            # is always the most recent — no separate max(created_at)
            # pass needed.
            summaries[root_id] = (count + 1, reply)

        return summaries

    async def assign_thread_to_ticket(
        self,
        root_interaction_id: UUID,
        ticket_id: UUID,
    ) -> None:
        """
        Moves an entire inbox thread (its root plus every reply
        filed under it) onto a ticket in one go — used when a
        pending email (or a whole conversation under it) is
        promoted to a ticket, so replies already exchanged before
        the ticket existed still show up on its timeline.
        """

        root = await self.get_by_id(root_interaction_id)
        if root is not None and root.ticket_id is None:
            root.ticket_id = ticket_id
            root.status = InteractionStatus.ASSIGNED

        thread = await self.list_thread(root_interaction_id)
        for reply in thread:
            reply.ticket_id = ticket_id
            reply.status = InteractionStatus.ASSIGNED

        await self.db.flush()

    async def get_latest_inbound_email_for_ticket(
        self,
        ticket_id: UUID,
    ) -> Interaction | None:
        """
        The most recent INBOUND email interaction on a ticket —
        used to build a reply's envelope (recipient address,
        In-Reply-To header) without the caller needing to know the
        ticket's email history.
        """

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.ticket_id == ticket_id,
                Interaction.interaction_type == "EMAIL",
            )
            .order_by(Interaction.created_at.desc())
            .limit(1)
        )

        return result.scalar_one_or_none()

    async def update(
        self,
        interaction: Interaction,
        data: InteractionUpdate,
    ) -> Interaction:

        update_data = data.model_dump(
            exclude_unset=True
        )

        for field, value in update_data.items():
            setattr(interaction, field, value)

        await self.db.flush()

        await self.db.refresh(interaction)

        return interaction

    async def assign_to_ticket(
        self,
        interaction: Interaction,
        ticket_id: UUID,
    ) -> Interaction:
        """
        Assign an inbox interaction to a ticket.

        Used when an agent creates a new ticket
        or attaches the email to an existing ticket.
        """

        interaction.ticket_id = ticket_id

        interaction.status = InteractionStatus.ASSIGNED

        await self.db.flush()

        await self.db.refresh(interaction)

        return interaction

    async def exists_by_message_id(
        self,
        message_id: str,
    ) -> bool:
        """
        Check whether an interaction with the given
        email message_id already exists.
        """

        result = await self.db.execute(
            select(Interaction.interaction_id).where(
                Interaction.message_id == message_id
            )
        )

        return result.scalar_one_or_none() is not None

    async def claim(
        self,
        interaction: Interaction,
        user_id: UUID,
    ) -> Interaction | None:
        """
        Atomically assigns an unclaimed, unticketed PENDING interaction
        to `user_id` — "Assign to me". Guarded by a conditional UPDATE
        (mirroring TicketRepository.claim's ticket-level race guard)
        rather than a plain ORM attribute set, so two agents clicking
        "Assign to me" on the same item at the same moment can't both
        win. Returns None when the guard fails (already claimed,
        already ticketed, or no longer pending).
        """

        result = await self.db.execute(
            update(Interaction)
            .where(
                Interaction.interaction_id == interaction.interaction_id,
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
                Interaction.claimed_by.is_(None),
            )
            .values(claimed_by=user_id, claimed_at=datetime.now(timezone.utc))
        )

        if result.rowcount == 0:
            return None

        await self.db.flush()
        await self.db.refresh(interaction)

        return interaction

    async def archive(
        self,
        interaction: Interaction,
    ) -> Interaction | None:
        """
        Atomically marks a pending, unticketed interaction IGNORED —
        the "Informational / Archive" reviewer decision: store it, no
        ticket, no work assignment, still searchable later via the
        "archived" inbox view. Same conditional-UPDATE race guard as
        claim, so an archive and a concurrent claim/convert-to-ticket
        can't both silently win.
        """

        result = await self.db.execute(
            update(Interaction)
            .where(
                Interaction.interaction_id == interaction.interaction_id,
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
            )
            .values(status=InteractionStatus.IGNORED)
        )

        if result.rowcount == 0:
            return None

        await self.db.flush()
        await self.db.refresh(interaction)

        return interaction


    async def set_tags(
        self,
        interaction: Interaction,
        tags: list[str],
    ) -> Interaction:
        """
        Full-replace of an interaction's tag list — no per-tag
        add/remove endpoint, the frontend always sends the complete
        set. Plain update, not a claim-style guard: tagging isn't a
        contested "only one winner" action the way claiming is.
        """

        interaction.tags = tags

        await self.db.flush()
        await self.db.refresh(interaction)

        return interaction

    async def set_folder(
        self,
        interaction: Interaction,
        folder_id: UUID | None,
    ) -> Interaction:
        """
        Assigns (or clears, if `folder_id` is None) which custom
        folder this item is filed under. Plain update — filing into a
        folder isn't a race-sensitive action.
        """

        interaction.folder_id = folder_id

        await self.db.flush()
        await self.db.refresh(interaction)

        return interaction

    async def hide(
        self,
        interaction: Interaction,
        removed_by: UUID | None,
    ) -> Interaction:
        """
        Soft-deletes an interaction.

        The interaction row is never removed from the
        database; it is simply marked as not visible,
        preserving the full ticket timeline and audit trail.
        """

        interaction.is_visible = False

        interaction.removed_by = removed_by

        interaction.removed_at = datetime.now(timezone.utc)

        await self.db.flush()

        await self.db.refresh(interaction)

        return interaction
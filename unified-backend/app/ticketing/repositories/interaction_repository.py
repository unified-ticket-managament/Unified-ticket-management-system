from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import exists, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from shared_models.models import Category, User

from app.core.impersonation_context import get_impersonator
from app.core.request_timing import timed_stage
from app.ticketing.enums import EscalationStatus, InteractionDirection, InteractionStatus, TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.ticket import Ticket
from app.ticketing.models.ticket_escalation import TicketEscalation
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

        # If the request that triggered this write is an impersonated
        # session, stamp the real actor here — `performed_by` above
        # stays whoever the caller already resolved (the target/
        # effective performer, unchanged business meaning); this is
        # purely additional. See app/core/impersonation_context.py.
        impersonator = get_impersonator()
        if impersonator is not None:
            interaction.impersonator_id, interaction.impersonator_name = impersonator

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
        client_company_id_filter: UUID | None = None,
        ticket_type_filter: str | None = None,
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
          DB call, from `current_user.categories` (a Team Lead may
          belong to more than one — see root CLAUDE.md's multi-
          category-users section), which `UserRepository.get_by_id`
          eager-loads at auth time.
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

        if client_company_id_filter is not None:
            conditions.append(Ticket.client_company_id == client_company_id_filter)

        if ticket_type_filter is not None:
            conditions.append(Ticket.ticket_type == ticket_type_filter)

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

    def _escalated_owner_condition(self, viewer_user_id: UUID):
        """
        True when the interaction's ticket has a non-CLOSED
        TicketEscalation row whose *current* owner_ids includes this
        viewer — mirrors TicketRepository._escalated_owner_condition
        exactly (same reasoning: a Team Lead/Account Manager only
        appears in owner_ids once the chain reaches their level; Site
        Lead/Super Admin once it reaches SITE_LEAD). Lets Mail's "My
        Claims" recognize a ticket handed to this viewer via
        escalation immediately, not only once the escalation is
        formally accepted and Ticket.agent_id is reassigned.
        """

        return exists().where(
            TicketEscalation.ticket_id == Ticket.ticket_id,
            TicketEscalation.status != EscalationStatus.CLOSED,
            TicketEscalation.owner_ids.contains([str(viewer_user_id)]),
        )

    async def list_inbox(
        self,
        account_manager_id: UUID | None = None,
        client_id: UUID | None = None,
        view: str = "pending",
        folder_id: UUID | None = None,
        ticket_types: list[str] | None = None,
        assigned_agent_id: UUID | None = None,
        extra_ticket_ids: list[UUID] | None = None,
        *,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        cursor: tuple[datetime, UUID] | None = None,
        category_filter: str | None = None,
        priority_filter: TicketPriority | None = None,
        account_manager_category_ids: list[UUID] | None = None,
    ) -> tuple[list[Interaction], int]:
        """
        The role-scoped inbox query — always over thread ROOTS
        (parent_interaction_id IS NULL, interaction_type == "EMAIL");
        replies are fetched separately via `list_thread` once a root
        is opened.

        - `account_manager_id` set: only mail belonging to clients
          that AM owns (a join against `clients`), OR'd with
          `account_manager_category_ids` when given (every CATEGORY-
          mailbox interaction — client_id IS NULL — whose category_id
          is one this Account Manager is Reporting Manager for, see
          ReportingManagerTeam). None (and `ticket_types`/
          `assigned_agent_id` also None) means "every client" — the
          Site Lead/Super Admin global inbox.
        - `client_id` set: further narrows to one client (the
          per-client filter on the inbox UI).
        - `folder_id` set: further narrows to one custom folder —
          orthogonal to `status` (a folder can hold items in any
          status), so this composes with any of the views below
          rather than being its own view. NOT orthogonal to
          view=="pending" specifically: a filed item (folder_id set,
          whether via a Rule's move_to_folder action or a manual
          PATCH /inbox/{id}/folder) is excluded from the "pending"
          Inbox view — see that branch below — since a user who has
          filed something away has, by definition, already triaged it
          out of the default Inbox. Still reachable via folder_id
          (any view) or view=="all".
        - `ticket_types` set: Team Lead scoping — only threads whose
          ticket is filed under one of these work-specialization
          categories (a Team Lead may belong to more than one — see
          root CLAUDE.md's multi-category-users section). Implemented
          as an INNER join against `tickets`, so this also implicitly
          restricts to ticketed threads only (a Team Lead never sees a
          still-pending, pre-ticket item — see the role propagation
          rules in InboxService.get_inbox).
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
        UI filters (distinct from `ticket_types`, which is Team Lead's
        own fixed role scoping) — previously applied client-side over
        whatever page happened to be loaded, which meant "show me
        every HIGH-priority thread" could silently miss matches
        outside the currently-fetched batch. Either one triggers the
        same join against `tickets` already used for
        `ticket_types`/`assigned_agent_id` scoping — an OUTER join,
        since `priority_filter` only ever matches a ticketed thread
        (priority doesn't exist pre-ticket) but `category_filter` has
        two representations: `Interaction.category_id` for a
        category-mailbox item that hasn't become a ticket yet, and
        `Ticket.ticket_type` (a denormalized copy) once it has. The
        category WHERE clause matches either; an INNER join here would
        silently drop every not-yet-ticketed match before that WHERE
        is even reached.
        """

        query = select(Interaction)

        if account_manager_id is not None or client_id is not None:
            # outerjoin (not join): a CATEGORY-mailbox interaction has
            # client_id IS NULL and therefore no matching `clients`
            # row at all — an INNER JOIN would silently drop it before
            # the account_manager_category_ids OR-condition below ever
            # gets a chance to match it. Harmless for every other
            # caller (client_id is still filtered by an explicit WHERE
            # below regardless of join type).
            query = query.outerjoin(Client, Client.client_id == Interaction.client_id)

        if account_manager_id is not None:
            account_manager_condition = Client.account_manager_id == account_manager_id
            if account_manager_category_ids:
                account_manager_condition = or_(
                    account_manager_condition,
                    Interaction.category_id.in_(account_manager_category_ids),
                )
            query = query.where(account_manager_condition)

        if client_id is not None:
            query = query.where(Interaction.client_id == client_id)

        needs_ticket_join = (
            ticket_types is not None
            or assigned_agent_id is not None
            or category_filter is not None
            or priority_filter is not None
        )
        if needs_ticket_join:
            query = query.outerjoin(Ticket, Ticket.ticket_id == Interaction.ticket_id)

        if ticket_types is not None:
            query = query.where(Ticket.ticket_type.in_(ticket_types))

        if assigned_agent_id is not None:
            # A ticket escalated to this user (Team Lead/Account
            # Manager/Site Lead — Staff never appears in an escalation's
            # owner_ids) counts as "assigned to me" here even before the
            # escalation is formally accepted and Ticket.agent_id is
            # reassigned — otherwise Mail's "My Claims" wouldn't reflect
            # ownership until acceptance, unlike the Tickets page's own
            # Escalated tab. Safe to include unconditionally: it's a
            # no-op for a Staff caller's own baseline scope.
            ownership_conditions = [
                Ticket.agent_id == assigned_agent_id,
                self._escalated_owner_condition(assigned_agent_id),
            ]
            if extra_ticket_ids:
                ownership_conditions.append(Ticket.ticket_id.in_(extra_ticket_ids))
            query = query.where(or_(*ownership_conditions))

        if category_filter is not None:
            query = query.outerjoin(Category, Category.category_id == Interaction.category_id)
            query = query.where(
                or_(
                    Ticket.ticket_type == category_filter,
                    Category.category_name == category_filter,
                )
            )

        if priority_filter is not None:
            query = query.where(Ticket.current_priority == priority_filter)

        if folder_id is not None:
            query = query.where(Interaction.folder_id == folder_id)

        query = query.where(
            Interaction.is_visible.is_(True),
            Interaction.interaction_type == "EMAIL",
            Interaction.parent_interaction_id.is_(None),
        )

        # direction == INBOUND excludes the agent's own Compose-created
        # roots (interaction_type=="EMAIL", parent_interaction_id IS
        # NULL, direction=OUTBOUND — see InteractionService.compose_email)
        # from the pre-ticket triage views. Without it a Compose row
        # (status=ASSIGNED at creation, ticket_id=None) satisfies the
        # "replied" predicate below and leaks into that view — a
        # confirmed bug this filter fixes. Deliberately not applied to
        # "ticketed": a Compose email that's later converted/attached to
        # a ticket must still show under Ticketed regardless of who
        # authored the founding message. Also not applied to "all" —
        # that's the separate, intentionally-comprehensive "All Inboxes"
        # escape hatch, not one of the named Mail folders.
        if view == "pending":
            query = query.where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
                Interaction.direction == InteractionDirection.INBOUND,
                # A filed item (folder_id set, whether by a Rule's
                # move_to_folder action or a manual drag via PATCH
                # /inbox/{id}/folder) has been deliberately triaged out
                # of the pending queue — it stays fully reachable via
                # view="all"&folder_id=X (subject to the normal folder
                # sharing/visibility rules), just no longer via the
                # default Inbox tab. Outlook-style "move to folder
                # removes it from Inbox" semantics.
                Interaction.folder_id.is_(None),
            )
        elif view == "replied":
            query = query.where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.ASSIGNED,
                Interaction.direction == InteractionDirection.INBOUND,
            )
        elif view == "ticketed":
            query = query.where(Interaction.ticket_id.isnot(None))
        elif view == "archived":
            query = query.where(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.IGNORED,
                Interaction.direction == InteractionDirection.INBOUND,
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
        ticket_types: list[str] | None = None,
        assigned_agent_id: UUID | None = None,
        extra_ticket_ids: list[UUID] | None = None,
        account_manager_category_ids: list[UUID] | None = None,
        shared_folder_ids: set[UUID] | None = None,
    ) -> dict[UUID, int]:
        """
        One grouped COUNT per custom folder, under the exact same
        role-scoping `list_inbox` applies for `view="all"` — backs
        the Mail sidebar's per-folder badges without the N full
        list-and-serialize round trips (one per folder) that used to
        require.

        `shared_folder_ids`, when given, are folder_ids the viewer has
        genuine sharing access to (see InboxService.get_folder_counts'
        own docstring) — counted with NO ownership scoping at all,
        merged in Python with the normally-scoped count for every
        other folder. Deliberately two separate queries, not one
        query with an OR'd WHERE: this method conditionally INNER
        JOINs `tickets` for Team Lead/Staff scoping, and that JOIN
        would silently drop a pre-ticket row (`ticket_id IS NULL`)
        before any WHERE/OR clause is even evaluated — a plain OR
        added to the same joined query would still lose exactly the
        rows this bypass exists to surface. Costs nothing extra when
        `shared_folder_ids` is empty/None (the common case for a
        viewer with no shared folders) — the second query is simply
        skipped.
        """

        scoped_counts = await self._count_by_folder_scoped(
            account_manager_id=account_manager_id,
            client_id=client_id,
            ticket_types=ticket_types,
            assigned_agent_id=assigned_agent_id,
            extra_ticket_ids=extra_ticket_ids,
            account_manager_category_ids=account_manager_category_ids,
            exclude_folder_ids=shared_folder_ids,
        )
        if not shared_folder_ids:
            return scoped_counts

        unrestricted_counts = await self._count_by_folder_unrestricted(
            folder_ids=shared_folder_ids, client_id=client_id
        )
        scoped_counts.update(unrestricted_counts)
        return scoped_counts

    async def _count_by_folder_scoped(
        self,
        account_manager_id: UUID | None = None,
        client_id: UUID | None = None,
        ticket_types: list[str] | None = None,
        assigned_agent_id: UUID | None = None,
        extra_ticket_ids: list[UUID] | None = None,
        account_manager_category_ids: list[UUID] | None = None,
        exclude_folder_ids: set[UUID] | None = None,
    ) -> dict[UUID, int]:
        query = select(Interaction.folder_id, func.count(Interaction.interaction_id))

        if account_manager_id is not None or client_id is not None:
            query = query.outerjoin(Client, Client.client_id == Interaction.client_id)

        if account_manager_id is not None:
            account_manager_condition = Client.account_manager_id == account_manager_id
            if account_manager_category_ids:
                account_manager_condition = or_(
                    account_manager_condition,
                    Interaction.category_id.in_(account_manager_category_ids),
                )
            query = query.where(account_manager_condition)

        if client_id is not None:
            query = query.where(Interaction.client_id == client_id)

        if ticket_types is not None or assigned_agent_id is not None:
            query = query.join(Ticket, Ticket.ticket_id == Interaction.ticket_id)

        if ticket_types is not None:
            query = query.where(Ticket.ticket_type.in_(ticket_types))

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
        )

        if exclude_folder_ids:
            query = query.where(Interaction.folder_id.notin_(exclude_folder_ids))

        query = query.group_by(Interaction.folder_id)

        result = await self.db.execute(query)

        return {folder_id: count for folder_id, count in result.all()}

    async def _count_by_folder_unrestricted(
        self,
        folder_ids: set[UUID],
        client_id: UUID | None = None,
    ) -> dict[UUID, int]:
        """
        Counts every visible EMAIL-root interaction in `folder_ids`
        with no ownership scoping at all (no Client/Ticket join,
        hence no risk of dropping a pre-ticket row) — only for folders
        already confirmed shared with the viewer. `client_id`, when
        given, is kept as an explicit narrowing filter (the same
        "further narrows to one client" role it plays everywhere
        else), never treated as ownership scoping.
        """

        query = select(Interaction.folder_id, func.count(Interaction.interaction_id)).where(
            Interaction.folder_id.in_(folder_ids),
            Interaction.is_visible.is_(True),
            Interaction.interaction_type == "EMAIL",
            Interaction.parent_interaction_id.is_(None),
        )

        if client_id is not None:
            query = query.where(Interaction.client_id == client_id)

        query = query.group_by(Interaction.folder_id)

        result = await self.db.execute(query)

        return {folder_id: count for folder_id, count in result.all()}

    async def count_by_view(
        self,
        account_manager_id: UUID | None = None,
        client_id: UUID | None = None,
        ticket_types: list[str] | None = None,
        assigned_agent_id: UUID | None = None,
        extra_ticket_ids: list[UUID] | None = None,
        account_manager_category_ids: list[UUID] | None = None,
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

        # Direction filters mirror list_inbox's own — see that method's
        # comment for why "ticketed"/the unfiltered "all" count are
        # deliberately exempt.
        query = select(
            func.count().filter(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.PENDING,
                Interaction.direction == InteractionDirection.INBOUND,
                Interaction.folder_id.is_(None),
            ),
            func.count().filter(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.ASSIGNED,
                Interaction.direction == InteractionDirection.INBOUND,
            ),
            func.count().filter(Interaction.ticket_id.isnot(None)),
            func.count().filter(
                Interaction.ticket_id.is_(None),
                Interaction.status == InteractionStatus.IGNORED,
                Interaction.direction == InteractionDirection.INBOUND,
            ),
            func.count(),
        )

        if account_manager_id is not None or client_id is not None:
            query = query.outerjoin(Client, Client.client_id == Interaction.client_id)

        if account_manager_id is not None:
            account_manager_condition = Client.account_manager_id == account_manager_id
            if account_manager_category_ids:
                account_manager_condition = or_(
                    account_manager_condition,
                    Interaction.category_id.in_(account_manager_category_ids),
                )
            query = query.where(account_manager_condition)

        if client_id is not None:
            query = query.where(Interaction.client_id == client_id)

        if ticket_types is not None or assigned_agent_id is not None:
            query = query.join(Ticket, Ticket.ticket_id == Interaction.ticket_id)

        if ticket_types is not None:
            query = query.where(Ticket.ticket_type.in_(ticket_types))

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
        Every brand-new Compose email the given user has authored
        (InteractionService.compose_email) — a thread ROOT
        (parent_interaction_id IS NULL), never a reply. Reply messages
        live under list_replied instead. This used to also OR in
        REPLY-type rows, which meant a message sent via Reply showed up
        under both "Sent" and "Replied" in the Mail UI — the two are
        now split so each folder means only what its name says.

        `dispatch_status == "SENT"` is required, not defensive padding:
        a row is created as PENDING_SEND before Graph is ever called
        (so Undo Send has something to cancel), and only flips to SENT
        once Graph actually confirms it — without this filter, a
        message still inside its Undo window, one Graph rejected
        (FAILED), or one the user canceled (CANCELED) all rendered
        identically to a real send.
        """

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.interaction_type == "EMAIL",
                Interaction.parent_interaction_id.is_(None),
                Interaction.direction == InteractionDirection.OUTBOUND,
                Interaction.performed_by == performed_by,
                Interaction.is_visible.is_(True),
                Interaction.dispatch_status == "SENT",
            )
            .order_by(Interaction.created_at.desc())
        )

        return list(result.scalars().all())

    async def list_replied(
        self,
        performed_by: UUID,
    ) -> list[Interaction]:
        """
        Every reply the given user has personally sent — pre-ticket or
        ticket-level alike, both created via the same REPLY/OUTBOUND
        shape (see `InteractionService.add_interaction_reply`/
        `add_reply`) — the counterpart to list_sent above, which is
        Compose-only. A sent reply's subject/client is resolved by the
        caller via `list_by_ids` on `parent_interaction_id`, same as
        list_sent's old merged behavior used to.

        `is_draft.is_(False)` is required, not defensive padding: a
        saved-but-unsent draft is also interaction_type=="REPLY",
        direction=OUTBOUND, is_visible=True — without this exclusion it
        would show up here as already "sent" while still sitting in
        Drafts (a real, separate bug this same split fixes).

        `dispatch_status == "SENT"` is required for the same reason as
        list_sent's own matching condition above: a reply is created
        PENDING_SEND before Graph is ever called (for Undo Send), and
        only becomes SENT once Graph actually confirms it — without
        this, a still-pending/FAILED/CANCELED reply rendered here
        identically to a real send.
        """

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.interaction_type == "REPLY",
                Interaction.direction == InteractionDirection.OUTBOUND,
                Interaction.performed_by == performed_by,
                Interaction.is_visible.is_(True),
                Interaction.is_draft.is_(False),
                Interaction.dispatch_status == "SENT",
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

    async def get_ticket_draft(
        self,
        ticket_id: UUID,
        performed_by: UUID,
        interaction_type: str,
    ) -> Interaction | None:
        """
        The given agent's active draft of the given type ("REPLY" or
        "INTERNAL_NOTE") on this ticket, if any — the ticket-scoped
        counterpart to get_draft above. A ticket draft has no thread
        root to be a child of (ticket_id itself is the scope,
        parent_interaction_id is always NULL) — enforced at the
        database level by ix_interactions_one_ticket_draft_per_agent_
        per_type. Same ORDER BY + LIMIT 1 defensive read as get_draft.
        """

        result = await self.db.execute(
            select(Interaction)
            .where(
                Interaction.ticket_id == ticket_id,
                Interaction.performed_by == performed_by,
                Interaction.interaction_type == interaction_type,
                Interaction.is_draft.is_(True),
                Interaction.is_visible.is_(True),
            )
            .order_by(Interaction.created_at.desc())
            .limit(1)
        )

        return result.scalars().first()

    async def list_stale_drafts(self, older_than: datetime) -> list[Interaction]:
        """
        Phase 2 hardening: every still-visible draft (is_draft=True)
        older than `older_than` — the scheduled draft-retention sweep's
        own query (app/core/draft_retention_scheduler.py). An abandoned
        compose/reply the user never explicitly discarded (tab closed,
        crash, navigated away) otherwise lingers, with its uploaded
        attachments, forever.
        """

        result = await self.db.execute(
            select(Interaction).where(
                Interaction.is_draft.is_(True),
                Interaction.is_visible.is_(True),
                Interaction.created_at < older_than,
            )
        )
        return list(result.scalars().all())

    async def list_stale_unclaimed_inline_images(
        self, older_than: datetime
    ) -> list[Interaction]:
        """
        Phase 2 hardening: every still-visible ATTACHMENT interaction
        minted purely to stage a pasted inline image
        (AttachmentService.upload_inline_image /
        InteractionService.upload_compose_inline_image — both set
        payload["is_inline"]=True) that was never reassigned onto a
        submitted reply/note/compose/forward and is older than
        `older_than`.

        The `payload["is_inline"]` condition is what keeps this from
        ever matching an ordinary, permanently-attached
        upload_attachment row (which has no `is_inline` payload key at
        all) — those must never be swept. A *consumed* inline image
        (one whose files were reassigned onto a real sent interaction)
        already has is_visible flipped False by that same reassignment
        path, so it's excluded by the is_visible.is_(True) condition
        here without needing a second, separate check.
        """

        result = await self.db.execute(
            select(Interaction).where(
                Interaction.interaction_type == "ATTACHMENT",
                Interaction.is_visible.is_(True),
                Interaction.payload["is_inline"].astext == "true",
                Interaction.created_at < older_than,
            )
        )
        return list(result.scalars().all())

    async def update_draft_message(
        self,
        interaction: Interaction,
        message: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        body_html: str | None = None,
    ) -> Interaction:
        """Overwrites a draft's saved text (and Cc/Bcc/body_html) in place — upsert's "update" half."""

        interaction.payload = {
            **interaction.payload,
            "message": message,
            "cc": cc if cc is not None else interaction.payload.get("cc", []),
            "bcc": bcc if bcc is not None else interaction.payload.get("bcc", []),
            # None means "no rich HTML for this save" — deliberately
            # overwrites any previously-saved body_html rather than
            # preserving it, mirroring how `message` itself is always
            # overwritten wholesale on every save (this is the same
            # upsert-the-whole-draft semantics, not a partial patch).
            "body_html": body_html,
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
        highest-priority thread-match signal, checked before
        in_reply_to/references (see EmailService.receive_email).
        """

        result = await self.db.execute(
            select(Interaction).where(Interaction.conversation_id == conversation_id)
        )

        return list(result.scalars().all())

    async def get_by_idempotency_key(
        self, idempotency_key: str, performed_by: UUID
    ) -> Interaction | None:
        """
        Looks up an interaction by its Send/Retry-Send idempotency key,
        scoped to the caller who set it — the same (performed_by, key)
        pair the partial unique index on dispatch_idempotency_key
        enforces (see the add_dispatch_idempotency_key migration), so
        this can never surface another user's interaction even given
        a guessed/reused key string.
        """

        result = await self.db.execute(
            select(Interaction).where(
                Interaction.dispatch_idempotency_key == idempotency_key,
                Interaction.performed_by == performed_by,
            )
        )

        return result.scalar_one_or_none()

    async def find_orphans_awaiting_parent(self, message_id: str) -> list[Interaction]:
        """
        Out-of-order delivery: finds every already-stored interaction
        whose in_reply_to_message_id/references named `message_id` —
        i.e. it arrived as a reply before its own original message
        did, so it had nothing to thread-match against yet at its own
        creation time (get_by_message_ids only ever looks *backward*).
        Called once the original itself lands, by
        EmailService._reconcile_orphaned_replies.

        The guard conditions (still parentless, unticketed, unclaimed,
        PENDING) mirror claim()/archive()'s own race-guard idiom —
        deliberately narrow: once an agent has acted on an orphan in
        any way, it's left alone rather than reparented out from under
        them. Matches on exact message_id equality only — the same
        signal already trusted for the forward-direction check — so
        this can never merge two unrelated emails.
        """

        result = await self.db.execute(
            select(Interaction).where(
                Interaction.parent_interaction_id.is_(None),
                Interaction.ticket_id.is_(None),
                Interaction.claimed_by.is_(None),
                Interaction.status == InteractionStatus.PENDING,
                or_(
                    Interaction.in_reply_to_message_id == message_id,
                    Interaction.references.contains([message_id]),
                ),
            )
        )

        return list(result.scalars().all())

    async def reparent(self, interaction: Interaction, new_parent_id: UUID) -> None:
        """
        Fixes up parent_interaction_id after the fact — the entire
        mutation find_orphans_awaiting_parent's reconciliation needs.
        Deliberately does not touch any other column (status, ticket_id,
        SLA-adjacent state): only the structural thread link changes,
        so list_thread/find_thread_root's existing recursive walk picks
        up the corrected nesting with no further change needed.
        """

        interaction.parent_interaction_id = new_parent_id
        await self.db.flush()

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

    async def try_transition_to_pending_send(
        self,
        interaction_id: UUID,
    ) -> Interaction | None:
        """
        Atomically moves a FAILED outbound interaction back to
        PENDING_SEND — Retry Send's own race guard, same conditional-
        UPDATE idiom as claim()/archive() above, so two concurrent
        retry clicks (or a retry racing the original send finally
        landing) can't both win. Returns None when the guard fails
        (not FAILED — already retried, already sent, or never a real
        send to begin with), the signal InteractionService.
        retry_failed_send uses to 400 "no longer retryable" rather
        than attempting a second dispatch.
        """

        result = await self.db.execute(
            update(Interaction)
            .where(
                Interaction.interaction_id == interaction_id,
                Interaction.dispatch_status == "FAILED",
            )
            .values(dispatch_status="PENDING_SEND", dispatch_error=None)
        )

        if result.rowcount == 0:
            return None

        await self.db.flush()

        return await self.get_by_id(interaction_id)

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

    async def clear_folder_for_folder_id(self, folder_id: UUID) -> int:
        """
        Bulk-clears folder_id (never the interaction row itself, its
        ticket_id, or anything else) for every interaction currently
        filed under `folder_id` — one UPDATE statement, not a per-row
        Python loop. The one caller is RuleService.delete's folder-
        cleanup step: when a rule-exclusively-owned folder is deleted,
        its messages must return to the normal Inbox (folder_id NULL)
        rather than being lost to the FK relationship. Returns the
        number of rows affected, for structured logging only.
        """

        result = await self.db.execute(
            update(Interaction)
            .where(Interaction.folder_id == folder_id)
            .values(folder_id=None)
        )
        return result.rowcount or 0

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
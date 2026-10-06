from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import String, cast, func, literal, select, union_all, update
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import Category, User

from app.ticketing.enums import SLAClockStatus, TicketStatus
from app.ticketing.models.ticket import Ticket
from app.ticketing.models.ticket_assignment import TicketAssignment
from app.ticketing.models.ticket_assignment_sla import TicketAssignmentSLA
from app.ticketing.models.ticket_category import TicketCategory

#ticket_assignment_repository.py

class TicketAccessContext:
    """
    The two per-ticket facts access_control's synchronous (no-DB)
    checks need beyond the Ticket row itself — attached onto a loaded
    Ticket as transient attributes by `hydrate_access_context` (see
    ensure_agent_can_view_ticket / ensure_agent_can_act_on_ticket).
    """

    __slots__ = ("active_assignee_ids", "category_names")

    def __init__(self) -> None:
        self.active_assignee_ids: set[UUID] = set()
        self.category_names: set[str] = set()


class TicketAssignmentRepository:
    """
    Owns ticket_assignments, ticket_categories and
    ticket_assignment_slas. Never commits — every write shares the
    request transaction (get_db commits once at the end), same as every
    other repository in this package.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------------------------------------------------------
    # Ticket lock
    # ---------------------------------------------------------

    async def lock_ticket(self, ticket_id: UUID) -> Ticket | None:
        """
        SELECT ... FOR UPDATE on the ticket row, re-reading it fresh
        (populate_existing) — serializes every multi-assignment
        mutation (and the universal close) on the same ticket, so two
        concurrent requests can never both observe "not closed" / "no
        primary yet" and both act on it. Held until the request
        transaction commits or rolls back.
        """

        result = await self.db.execute(
            select(Ticket)
            .where(Ticket.ticket_id == ticket_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    # ---------------------------------------------------------
    # Access context (batch)
    # ---------------------------------------------------------

    async def load_access_context(
        self, ticket_ids: list[UUID]
    ) -> dict[UUID, TicketAccessContext]:
        """
        One round trip (UNION ALL) for both the active assignee ids and
        the category names of every given ticket.
        """

        contexts: dict[UUID, TicketAccessContext] = {
            ticket_id: TicketAccessContext() for ticket_id in ticket_ids
        }
        if not ticket_ids:
            return contexts

        assignees = select(
            TicketAssignment.ticket_id.label("ticket_id"),
            literal("U").label("kind"),
            cast(TicketAssignment.user_id, String).label("value"),
        ).where(
            TicketAssignment.ticket_id.in_(ticket_ids),
            TicketAssignment.removed_at.is_(None),
        )
        categories = (
            select(
                TicketCategory.ticket_id.label("ticket_id"),
                literal("C").label("kind"),
                cast(Category.category_name, String).label("value"),
            )
            .join(Category, Category.category_id == TicketCategory.category_id)
            .where(TicketCategory.ticket_id.in_(ticket_ids))
        )

        rows = (await self.db.execute(union_all(assignees, categories))).all()
        for ticket_id, kind, value in rows:
            context = contexts[ticket_id]
            if kind == "U":
                context.active_assignee_ids.add(UUID(value))
            else:
                context.category_names.add(value)
        return contexts

    async def hydrate_access_context(self, tickets: list[Ticket]) -> None:
        """
        Attaches `active_assignee_ids` / `category_names` onto each
        loaded Ticket. A ticket with no ticket_categories row (only
        possible for a category name that matched no categories row at
        backfill time) falls back to its legacy ticket_type, so it is
        never accidentally hidden.
        """

        if not tickets:
            return
        contexts = await self.load_access_context([t.ticket_id for t in tickets])
        for ticket in tickets:
            context = contexts[ticket.ticket_id]
            category_names = set(context.category_names)
            if ticket.ticket_type:
                category_names.add(ticket.ticket_type)
            assignee_ids = set(context.active_assignee_ids)
            if ticket.agent_id is not None:
                assignee_ids.add(ticket.agent_id)
            ticket.active_assignee_ids = assignee_ids
            ticket.category_names = category_names

    # ---------------------------------------------------------
    # Assignments
    # ---------------------------------------------------------

    async def list_active(self, ticket_id: UUID) -> list[TicketAssignment]:
        result = await self.db.execute(
            select(TicketAssignment)
            .where(
                TicketAssignment.ticket_id == ticket_id,
                TicketAssignment.removed_at.is_(None),
            )
            .order_by(TicketAssignment.is_primary.desc(), TicketAssignment.assigned_at)
        )
        return list(result.scalars().all())

    async def list_active_for_tickets(
        self, ticket_ids: list[UUID]
    ) -> dict[UUID, list[tuple[TicketAssignment, str | None]]]:
        """
        Batch load (assignment, user name) for a page of tickets — one
        query, no per-ticket N+1.
        """

        grouped: dict[UUID, list[tuple[TicketAssignment, str | None]]] = defaultdict(list)
        if not ticket_ids:
            return grouped
        result = await self.db.execute(
            select(TicketAssignment, User.name)
            .join(User, User.user_id == TicketAssignment.user_id)
            .where(
                TicketAssignment.ticket_id.in_(ticket_ids),
                TicketAssignment.removed_at.is_(None),
            )
            .order_by(TicketAssignment.is_primary.desc(), TicketAssignment.assigned_at)
        )
        for assignment, name in result.all():
            grouped[assignment.ticket_id].append((assignment, name))
        return grouped

    async def get(self, assignment_id: UUID) -> TicketAssignment | None:
        result = await self.db.execute(
            select(TicketAssignment).where(TicketAssignment.assignment_id == assignment_id)
        )
        return result.scalar_one_or_none()

    async def get_active_for_user(
        self, ticket_id: UUID, user_id: UUID
    ) -> TicketAssignment | None:
        result = await self.db.execute(
            select(TicketAssignment).where(
                TicketAssignment.ticket_id == ticket_id,
                TicketAssignment.user_id == user_id,
                TicketAssignment.removed_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_primary(self, ticket_id: UUID) -> TicketAssignment | None:
        result = await self.db.execute(
            select(TicketAssignment).where(
                TicketAssignment.ticket_id == ticket_id,
                TicketAssignment.is_primary.is_(True),
                TicketAssignment.removed_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def add(self, assignment: TicketAssignment) -> TicketAssignment:
        self.db.add(assignment)
        await self.db.flush()
        return assignment

    async def flush(self) -> None:
        await self.db.flush()

    async def close_all_active(
        self, ticket_id: UUID, *, closed_at: datetime, closed_by: UUID | None
    ) -> None:
        await self.db.execute(
            update(TicketAssignment)
            .where(
                TicketAssignment.ticket_id == ticket_id,
                TicketAssignment.removed_at.is_(None),
            )
            .values(
                status=TicketStatus.CLOSED,
                status_changed_at=closed_at,
                closed_at=closed_at,
                closed_by=closed_by,
                updated_at=closed_at,
            )
            .execution_options(synchronize_session="fetch")
        )

    # ---------------------------------------------------------
    # Categories
    # ---------------------------------------------------------

    async def list_categories(
        self, ticket_id: UUID
    ) -> list[tuple[TicketCategory, str]]:
        result = await self.db.execute(
            select(TicketCategory, Category.category_name)
            .join(Category, Category.category_id == TicketCategory.category_id)
            .where(TicketCategory.ticket_id == ticket_id)
            .order_by(TicketCategory.is_primary.desc(), TicketCategory.assigned_at)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def list_categories_for_tickets(
        self, ticket_ids: list[UUID]
    ) -> dict[UUID, list[tuple[TicketCategory, str]]]:
        grouped: dict[UUID, list[tuple[TicketCategory, str]]] = defaultdict(list)
        if not ticket_ids:
            return grouped
        result = await self.db.execute(
            select(TicketCategory, Category.category_name)
            .join(Category, Category.category_id == TicketCategory.category_id)
            .where(TicketCategory.ticket_id.in_(ticket_ids))
            .order_by(TicketCategory.is_primary.desc(), TicketCategory.assigned_at)
        )
        for ticket_category, name in result.all():
            grouped[ticket_category.ticket_id].append((ticket_category, name))
        return grouped

    async def get_category_by_id(self, category_id: UUID) -> Category | None:
        result = await self.db.execute(
            select(Category).where(Category.category_id == category_id)
        )
        return result.scalar_one_or_none()

    async def get_category_by_name(self, category_name: str) -> Category | None:
        result = await self.db.execute(
            select(Category).where(Category.category_name == category_name)
        )
        return result.scalar_one_or_none()

    async def get_ticket_category(
        self, ticket_id: UUID, category_id: UUID
    ) -> TicketCategory | None:
        result = await self.db.execute(
            select(TicketCategory).where(
                TicketCategory.ticket_id == ticket_id,
                TicketCategory.category_id == category_id,
            )
        )
        return result.scalar_one_or_none()

    async def add_category(self, ticket_category: TicketCategory) -> TicketCategory:
        self.db.add(ticket_category)
        await self.db.flush()
        return ticket_category

    async def delete_category(self, ticket_category: TicketCategory) -> None:
        await self.db.delete(ticket_category)
        await self.db.flush()

    # ---------------------------------------------------------
    # Assignment SLA runs
    # ---------------------------------------------------------

    async def get_live_run(self, assignment_id: UUID) -> TicketAssignmentSLA | None:
        result = await self.db.execute(
            select(TicketAssignmentSLA).where(
                TicketAssignmentSLA.assignment_id == assignment_id,
                TicketAssignmentSLA.status != SLAClockStatus.COMPLETED,
            )
        )
        return result.scalar_one_or_none()

    async def list_live_runs_for_ticket(self, ticket_id: UUID) -> list[TicketAssignmentSLA]:
        result = await self.db.execute(
            select(TicketAssignmentSLA).where(
                TicketAssignmentSLA.ticket_id == ticket_id,
                TicketAssignmentSLA.status != SLAClockStatus.COMPLETED,
            )
        )
        return list(result.scalars().all())

    async def list_runs_for_ticket(self, ticket_id: UUID) -> list[TicketAssignmentSLA]:
        result = await self.db.execute(
            select(TicketAssignmentSLA)
            .where(TicketAssignmentSLA.ticket_id == ticket_id)
            .order_by(TicketAssignmentSLA.assignment_id, TicketAssignmentSLA.run_number)
        )
        return list(result.scalars().all())

    async def next_run_number(self, assignment_id: UUID) -> int:
        result = await self.db.execute(
            select(func.coalesce(func.max(TicketAssignmentSLA.run_number), 0)).where(
                TicketAssignmentSLA.assignment_id == assignment_id
            )
        )
        return int(result.scalar_one()) + 1

    async def add_run(self, run: TicketAssignmentSLA) -> TicketAssignmentSLA:
        self.db.add(run)
        await self.db.flush()
        return run

    async def list_running_overdue_unbreached(
        self, now: datetime, limit: int = 500
    ) -> list[TicketAssignmentSLA]:
        """Sweep path — newly breached runs only (breached_at IS NULL)."""

        result = await self.db.execute(
            select(TicketAssignmentSLA)
            .where(
                TicketAssignmentSLA.status == SLAClockStatus.RUNNING,
                TicketAssignmentSLA.due_at < now,
                TicketAssignmentSLA.breached_at.is_(None),
            )
            .limit(limit)
        )
        return list(result.scalars().all())

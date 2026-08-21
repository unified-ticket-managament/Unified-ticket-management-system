# user_repository.py

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from shared_models.models import Category, Role, User
from shared_models.models.user_category import user_categories

STAFF_ROLE_NAME = "Staff"
ACCOUNT_MANAGER_ROLE_NAME = "Account Manager"


class UserRepository:
    """
    Read access to the shared `users` / `roles` tables
    (owned by the RBAC service, not this backend).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: UUID) -> User | None:
        # joinedload (one SQL statement, LEFT OUTER JOINs), not
        # selectinload (a separate round trip per relationship) — both
        # `role` and `category` are many-to-one from User's side (at
        # most one related row each), so a join can't fan out/duplicate
        # rows the way it would for a one-to-many relationship. This
        # runs on every authenticated request in the whole app (see
        # app/dependencies/auth.py's get_current_user), so collapsing
        # it from 3 round trips (user, role, category) to 1 matters
        # far beyond just this one call site — confirmed via this
        # session's Server-Timing investigation that each round trip
        # to this DB costs several hundred ms of latency regardless of
        # query complexity, so round-trip *count* is what actually
        # drove the real ~10s Interactions-tab load, not query cost.
        result = await self.db.execute(
            select(User)
            .options(
                joinedload(User.role),
                joinedload(User.category),
                selectinload(User.categories),
            )
            .where(User.user_id == user_id)
        )
        return result.unique().scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User)
            .options(joinedload(User.role))
            .where(func.lower(User.email) == email.lower())
        )
        return result.unique().scalar_one_or_none()

    async def list_by_ids(self, user_ids: list[UUID]) -> list[User]:
        """
        Batch fetch with `role` joinedloaded (needed to tell a self-
        claimed Team Lead apart from a self-claimed Account
        Manager/Site Lead/Super Admin — see sla_escalation_rules.
        resolve_team_lead) — used by the SLA sweep to resolve every
        claimed ticket's assigned agent in one query instead of a
        get_by_id call per clock, same convention as
        TicketRepository.list_by_ids / ClientRepository.list_by_ids.
        """

        if not user_ids:
            return []

        result = await self.db.execute(
            select(User)
            .options(joinedload(User.role))
            .where(User.user_id.in_(user_ids))
        )
        return list(result.unique().scalars().all())

    async def get_names_by_ids(self, user_ids: list[UUID]) -> dict[UUID, str]:
        """
        Batch-resolves user_id -> display name. Used to enrich
        ticket responses with client_name / agent_name without
        an N+1 query per ticket.
        """

        if not user_ids:
            return {}

        result = await self.db.execute(
            select(User.user_id, User.name).where(User.user_id.in_(user_ids))
        )
        return dict(result.all())

    async def get_active_emails_by_ids(self, user_ids: list[UUID]) -> dict[UUID, str]:
        """
        Batch-resolves user_id -> email address for active users only —
        used by the centralized notification-email feature
        (app/notifications/email_notifier.py), which can be handed a
        recipient set sourced from an arbitrary notify() call and must
        not email someone who's been deactivated. Kept as its own
        method rather than widening get_names_by_ids' existing
        (user_id, name) shape, which other callers already rely on.
        """

        if not user_ids:
            return {}

        result = await self.db.execute(
            select(User.user_id, User.email).where(
                User.user_id.in_(user_ids), User.is_active.is_(True)
            )
        )
        return dict(result.all())

    async def get_active_account_manager_ids(self, user_ids: list[UUID]) -> set[UUID]:
        """
        Batch-checks which of the given user_ids are CURRENTLY active
        Account Manager-role users. Used to flag a client whose mapped
        account_manager_id has "soft-orphaned" — the FK still points
        at a real user, but that user's role changed (or they were
        deactivated) after the client was created, and nothing
        revalidates that later.
        """

        if not user_ids:
            return set()

        result = await self.db.execute(
            select(User.user_id)
            .join(Role, Role.role_id == User.role_id)
            .where(
                User.user_id.in_(user_ids),
                Role.name == ACCOUNT_MANAGER_ROLE_NAME,
                User.is_active.is_(True),
            )
        )
        return set(result.scalars().all())

    async def list_all_active(self) -> list[User]:
        """
        Every active user, any role, company-wide — unlike every other
        listing method on this class (and RBAC's own `UserService.
        list_users`, which scopes Staff to themselves and Account
        Manager/Team Lead to their reporting subtree), this one is
        deliberately unscoped. Backs the Internal Note "To" recipient
        picker (see InteractionService.list_internal_note_recipients),
        which by explicit product requirement must let any eligible
        active platform user address any other — reusing RBAC's own
        `GET /api/v1/users` there would have inherited its
        hierarchy-scoping (wrong for this feature) and its `role:view`-
        gated `GET /api/v1/roles` call for role labels (which most
        roles, Staff included, don't hold by default) — neither of
        which this feature is allowed to change, since doing so would
        alter RBAC's own general-purpose user-management behavior.
        """

        result = await self.db.execute(
            select(User)
            .options(joinedload(User.role))
            .where(User.is_active.is_(True))
            .order_by(User.name)
        )
        return list(result.unique().scalars().all())

    async def list_active_by_role_name(self, role_name: str) -> list[User]:
        result = await self.db.execute(
            select(User)
            .join(Role, Role.role_id == User.role_id)
            .where(
                func.lower(Role.name) == role_name.lower(),
                User.is_active.is_(True),
            )
            .order_by(User.user_id)
        )
        return list(result.scalars().all())

    async def list_active_by_role_and_category(
        self, role_name: str, category_name: str
    ) -> list[User]:
        """
        Same shape as list_active_staff_by_category, generalized to any
        role — used to resolve "who can review edit-access requests for
        this ticket's category" (Team Lead, category-scoped) without
        hardcoding Staff.

        `category_name` is a ticket's own `ticket_type` string, plain
        text compared against `categories.category_name` (also plain
        text — categories are created dynamically at runtime, see
        shared_models.models.Category). A category_name matching no
        real category (e.g. corrupted/garbage test data) simply joins
        to zero rows here — "no one to find," the same as a valid
        category with no Team Lead configured yet. Never raises: this
        is a plain string comparison, not an enum cast, so there is no
        Postgres `InvalidTextRepresentationError` class of failure to
        guard against here at all.
        """

        result = await self.db.execute(
            select(User)
            .join(Role, Role.role_id == User.role_id)
            .join(user_categories, user_categories.c.user_id == User.user_id)
            .join(Category, Category.category_id == user_categories.c.category_id)
            .where(
                func.lower(Role.name) == role_name.lower(),
                User.is_active.is_(True),
                Category.category_name == category_name,
            )
            .order_by(User.user_id)
            .distinct()
        )
        return list(result.scalars().all())

    async def list_active_user_ids_by_category(self, category_name: str) -> set[UUID]:
        """
        Every active user's id (any role) belonging to category_name via
        the many-to-many user_categories relationship — a category_name
        matching no real category just means "no one to find" (a plain
        string join against zero rows, never a Postgres enum-cast
        error — see list_active_by_role_and_category's own docstring).
        Used to narrow an already-authorized candidate set (e.g.
        InteractionService.get_transfer_candidates) by category without
        a per-role join.
        """

        result = await self.db.execute(
            select(User.user_id)
            .join(user_categories, user_categories.c.user_id == User.user_id)
            .join(Category, Category.category_id == user_categories.c.category_id)
            .where(
                User.is_active.is_(True),
                Category.category_name == category_name,
            )
            .distinct()
        )
        return set(result.scalars().all())

    async def list_active_by_role_and_manager(
        self, role_name: str, manager_id: UUID
    ) -> list[User]:
        """
        Active users of the given role reporting (via `manager_id`) to
        one specific Account Manager — used to scope the Create Ticket
        "Assigned To" picker's Team Lead/Staff options to the acting
        Account Manager's own reports, not every Team Lead/Staff
        company-wide.
        """

        result = await self.db.execute(
            select(User)
            .join(Role, Role.role_id == User.role_id)
            .where(
                func.lower(Role.name) == role_name.lower(),
                User.manager_id == manager_id,
                User.is_active.is_(True),
            )
            .order_by(User.name)
        )
        return list(result.scalars().all())

    async def list_active_staff_by_teamlead(self, teamlead_id: UUID) -> list[User]:
        """
        Active Staff reporting (via `teamlead_id`) to one specific
        Team Lead — used to scope a Team Lead's own "Assigned To"
        Staff picker on the Create Ticket dialog.
        """

        result = await self.db.execute(
            select(User)
            .join(Role, Role.role_id == User.role_id)
            .where(
                func.lower(Role.name) == STAFF_ROLE_NAME.lower(),
                User.teamlead_id == teamlead_id,
                User.is_active.is_(True),
            )
            .order_by(User.name)
        )
        return list(result.scalars().all())

    async def list_active_staff_by_teamlead_ids(
        self, teamlead_ids: list[UUID]
    ) -> list[User]:
        """
        Active Staff reporting directly to any of the given Team Leads
        (`User.teamlead_id`) — one batched `IN (...)` query for however
        many Team Leads a category resolves to (a category can have
        more than one), matching this repo's existing batch-lookup
        convention (get_names_by_ids, TicketRepository.list_by_ids)
        rather than one query per Team Lead. Used by the SLA sweep's
        "unclaimed ticket" escalation path to notify a whole team, not
        just its Team Lead(s).
        """

        if not teamlead_ids:
            return []

        result = await self.db.execute(
            select(User)
            .join(Role, Role.role_id == User.role_id)
            .where(
                func.lower(Role.name) == STAFF_ROLE_NAME.lower(),
                User.is_active.is_(True),
                User.teamlead_id.in_(teamlead_ids),
            )
            .order_by(User.user_id)
        )
        return list(result.scalars().all())

    async def list_active_staff_by_category(self, category_name: str) -> list[User]:
        """
        Active Staff belonging to one work-specialization category
        (AR, Referral, Coding, ...) — used to scope the "assign to
        staff" ticket picker to the ticket's own category/team,
        instead of listing every Staff member company-wide.

        See list_active_by_role_and_category's own docstring for why
        an invalid `category_name` naturally yields "no one to find"
        without ever risking a Postgres enum-cast error.
        """

        result = await self.db.execute(
            select(User)
            .join(Role, Role.role_id == User.role_id)
            .join(user_categories, user_categories.c.user_id == User.user_id)
            .join(Category, Category.category_id == user_categories.c.category_id)
            .where(
                func.lower(Role.name) == STAFF_ROLE_NAME.lower(),
                User.is_active.is_(True),
                Category.category_name == category_name,
            )
            .order_by(User.user_id)
            .distinct()
        )
        return list(result.scalars().all())

    async def get_active_staff_by_id(self, user_id: UUID) -> User | None:
        result = await self.db.execute(
            select(User)
            .join(Role, Role.role_id == User.role_id)
            .where(
                User.user_id == user_id,
                func.lower(Role.name) == STAFF_ROLE_NAME.lower(),
                User.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_staff_by_name(self, name: str) -> User | None:
        result = await self.db.execute(
            select(User)
            .join(Role, Role.role_id == User.role_id)
            .where(
                func.lower(User.name) == name.lower(),
                func.lower(Role.name) == STAFF_ROLE_NAME.lower(),
                User.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

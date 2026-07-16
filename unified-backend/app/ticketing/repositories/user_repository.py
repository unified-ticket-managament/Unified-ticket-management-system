# user_repository.py

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from shared_models.models import Category, Role, User
from shared_models.models.category import CategoryName

STAFF_ROLE_NAME = "Staff"
ACCOUNT_MANAGER_ROLE_NAME = "Account Manager"

# Valid values of the category_name_enum Postgres type, computed once
# at import time — see list_active_by_role_and_category's own
# docstring for why this is checked in Python before ever reaching the
# database.
_VALID_CATEGORY_NAMES = {member.value for member in CategoryName}


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
            .options(joinedload(User.role), joinedload(User.category))
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

    async def get_emails_by_ids(self, user_ids: list[UUID]) -> dict[UUID, str]:
        """
        Batch-resolves user_id -> email address — used to send real
        outbound notification email (SLA breach escalations) to a
        resolved recipient set without a lookup per recipient. Kept as
        its own method rather than widening get_names_by_ids' existing
        (user_id, name) shape, which other callers already rely on.
        """

        if not user_ids:
            return {}

        result = await self.db.execute(
            select(User.user_id, User.email).where(User.user_id.in_(user_ids))
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

        `category_name` is a ticket's own `ticket_type` string, not
        something validated at ticket-creation time against the real
        `category_name_enum` values — a ticket with corrupted/garbage
        test data (`ticket_type="string"`, say) reaching this method
        would otherwise have Postgres reject the implicit enum
        comparison with `InvalidTextRepresentationError` mid-query.
        That's bad enough on its own for a single caller
        (`manual_escalate`'s route), but far worse for
        `SLASweepService`: it calls this (via
        `EscalationService._resolve_owners_for_level`) from inside a
        per-clock `db.begin_nested()` SAVEPOINT specifically so one
        ticket's failure can't affect another's — confirmed live that
        it doesn't actually hold up against this specific error class,
        with the session ending up unable to serve later queries in
        the same request at all (surfacing as a confusing
        `MissingGreenlet` on a *different*, unrelated ticket later in
        the same sweep tick, not the original enum error). Validating
        in Python first, before the query ever reaches the database,
        sidesteps the whole question of whether a SAVEPOINT rollback
        can cleanly recover from this — an invalid category_name now
        just means "no one to find," the same as a valid category with
        no Team Lead configured yet.
        """

        if category_name not in _VALID_CATEGORY_NAMES:
            return []

        result = await self.db.execute(
            select(User)
            .join(Role, Role.role_id == User.role_id)
            .join(Category, Category.category_id == User.category_id)
            .where(
                func.lower(Role.name) == role_name.lower(),
                User.is_active.is_(True),
                Category.category_name == category_name,
            )
            .order_by(User.user_id)
        )
        return list(result.scalars().all())

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
        (Eligibility, AR, Claims, ...) — used to scope the "assign to
        staff" ticket picker to the ticket's own category/team,
        instead of listing every Staff member company-wide.

        See list_active_by_role_and_category's own docstring for why
        an invalid `category_name` is checked in Python and treated as
        "no one to find" rather than reaching the database at all.
        """

        if category_name not in _VALID_CATEGORY_NAMES:
            return []

        result = await self.db.execute(
            select(User)
            .join(Role, Role.role_id == User.role_id)
            .join(Category, Category.category_id == User.category_id)
            .where(
                func.lower(Role.name) == STAFF_ROLE_NAME.lower(),
                User.is_active.is_(True),
                Category.category_name == category_name,
            )
            .order_by(User.user_id)
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

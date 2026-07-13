# user_repository.py

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from shared_models.models import Category, Role, User

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
        """

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

    async def list_active_staff_by_category(self, category_name: str) -> list[User]:
        """
        Active Staff belonging to one work-specialization category
        (Eligibility, AR, Claims, ...) — used to scope the "assign to
        staff" ticket picker to the ticket's own category/team,
        instead of listing every Staff member company-wide.
        """

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

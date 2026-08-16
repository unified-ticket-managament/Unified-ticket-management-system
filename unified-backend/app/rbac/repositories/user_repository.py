from uuid import UUID

from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from shared_models.models import Role, User
from shared_models.models.user_category import user_categories

from .base import BaseRepository


class UserRepository(BaseRepository):
    """
    Repository for User database operations.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    # --------------------------------------------------
    # Create
    # --------------------------------------------------

    async def create(self, user: User) -> User:
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    # --------------------------------------------------
    # Read
    # --------------------------------------------------

    async def get_by_id(self, user_id: UUID) -> User | None:
        # joinedload (one round trip), not selectinload (a separate
        # one per relationship) — both `role` and `category` are
        # many-to-one from User's side, so no row-fanout risk. login/
        # refresh_token now need `.category` too (to embed its name in
        # the JWT — see AuthService), not just `.role` as before.
        # `categories` (the new many-to-many collection) is loaded via
        # a separate selectinload — a collection relationship can't
        # safely share the same joinedload round trip as the two
        # scalar ones above without row fanout.
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
            .options(
                joinedload(User.role),
                joinedload(User.category),
                selectinload(User.categories),
            )
            .where(User.email == email)
        )

        return result.unique().scalar_one_or_none()

    async def get_all(
        self,
        page: int = 1,
        page_size: int = 10,
        search: str | None = None,
        category_id: UUID | None = None,
        category_ids: list[UUID] | None = None,
        visible_user_ids: set[UUID] | None = None,
    ) -> tuple[list[User], int]:
        """
        Returns:
            users,
            total_count

        `visible_user_ids`, when provided, restricts the result to
        exactly that set of user ids — the caller's own
        reporting-hierarchy scope (see UserService.list_users, which
        resolves this via OrganizationService.get_subordinate_user_ids
        for Account Manager/Team Lead, or a self-only set for Staff).
        `None` means unrestricted (Super Admin/Site Lead). An empty
        set correctly yields zero rows via `User.user_id.in_(())`
        rather than being mistaken for "no filter."

        `category_id` (legacy singular) and `category_ids` (new,
        multi-category-aware) are both accepted and merged into one
        any-match filter — a user matching ANY of the requested
        categories is included, exactly once (JOIN against
        `user_categories` + `.distinct()`, never a per-matched-category
        duplicate row).
        """

        merged_category_ids: list[UUID] = list(category_ids or [])
        if category_id is not None and category_id not in merged_category_ids:
            merged_category_ids.append(category_id)

        query = (
            select(User)
            .options(selectinload(User.role), selectinload(User.categories))
        )

        count_query = select(func.count(func.distinct(User.user_id))).select_from(User)

        if search:
            pattern = f"%{search}%"

            search_filter = or_(
                User.name.ilike(pattern),
                User.email.ilike(pattern),
                User.employee_number.ilike(pattern),
            )

            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        if merged_category_ids:
            query = (
                query.join(user_categories, user_categories.c.user_id == User.user_id)
                .where(user_categories.c.category_id.in_(merged_category_ids))
                .distinct()
            )
            count_query = count_query.join(
                user_categories, user_categories.c.user_id == User.user_id
            ).where(user_categories.c.category_id.in_(merged_category_ids))

        if visible_user_ids is not None:
            query = query.where(User.user_id.in_(visible_user_ids))
            count_query = count_query.where(User.user_id.in_(visible_user_ids))

        total = (
            await self.db.execute(count_query)
        ).scalar_one()

        result = await self.db.execute(
            query
            .order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        users = result.unique().scalars().all()

        return list(users), total

    # --------------------------------------------------
    # Update
    # --------------------------------------------------

    async def update(self, user: User) -> User:
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def bump_permission_version_for_role(self, role_id: UUID) -> None:
        """
        A role's own permission set changing (grant/revoke/replace,
        see RolePermissionService) affects every user who holds that
        role, not just one — one bulk UPDATE, not a per-row Python
        loop, so this stays cheap regardless of how many users share
        the role. See User.permission_version's own docstring and
        app/core/rbac_cache.py for what this actually invalidates.
        """

        await self.db.execute(
            update(User)
            .where(User.role_id == role_id)
            .values(permission_version=User.permission_version + 1)
        )

    # --------------------------------------------------
    # Delete
    # --------------------------------------------------

    async def delete(self, user: User) -> None:
        await self.db.delete(user)
        await self.db.flush()

    # --------------------------------------------------
    # Utility Methods
    # --------------------------------------------------

    async def exists(self, email: str) -> bool:
        result = await self.db.execute(
            select(User.user_id)
            .where(User.email == email)
        )

        return result.scalar_one_or_none() is not None

    async def get_by_role(
        self,
        role_id: UUID,
    ) -> list[User]:
        # is_active filtered for consistency with every "active"-
        # prefixed sibling method in ticketing's own UserRepository —
        # this method (and get_by_manager_and_role/get_by_teamlead/
        # get_by_category below) previously had no such filter, so a
        # deactivated user could still appear as a live node in the
        # Organization Chart (OrganizationService is this method's
        # only real caller).

        result = await self.db.execute(
            select(User)
            .options(
                selectinload(User.role),
                selectinload(User.category),
                selectinload(User.categories),
            )
            .where(User.role_id == role_id, User.is_active.is_(True))
            .order_by(User.name)
        )

        return list(result.scalars().all())

    async def list_active_by_role_name(self, role_name: str) -> list[User]:
        """
        Same shape as get_by_role, keyed by role name instead of an
        already-known role_id — used to resolve actual notification
        recipients from a role name (e.g. permission-request eligible
        approver roles), which callers only ever have as a string.
        """

        result = await self.db.execute(
            select(User)
            .options(selectinload(User.role))
            .join(Role, Role.role_id == User.role_id)
            .where(
                func.lower(Role.name) == role_name.lower(),
                User.is_active.is_(True),
            )
            .order_by(User.name)
        )

        return list(result.scalars().all())

    async def get_by_manager_and_role(
        self,
        manager_id: UUID,
        role_id: UUID,
    ) -> list[User]:

        result = await self.db.execute(
            select(User)
            .options(
                selectinload(User.role),
                selectinload(User.category),
                selectinload(User.categories),
            )
            .where(
                User.manager_id == manager_id,
                User.role_id == role_id,
                User.is_active.is_(True),
            )
            .order_by(User.name)
        )

        return list(result.scalars().all())

    async def get_by_teamlead(
        self,
        teamlead_id: UUID,
    ) -> list[User]:

        result = await self.db.execute(
            select(User)
            .options(
                selectinload(User.role),
                selectinload(User.category),
                selectinload(User.categories),
            )
            .where(User.teamlead_id == teamlead_id, User.is_active.is_(True))
            .order_by(User.name)
        )

        return list(result.scalars().all())

    async def get_direct_reports(
        self,
        user_id: UUID,
    ) -> list[User]:
        """
        Every active user whose `reporting_manager_id` points at
        `user_id` — the Organization Chart's sole source of truth (see
        OrganizationService.get_chart_for_user). Deliberately NOT
        `manager_id`/`teamlead_id` (those still drive
        get_by_manager_and_role/get_by_teamlead's role-shaped queries
        used elsewhere, e.g. get_subordinate_user_ids's permission-
        override-scoping traversal, which must stay on the old fields
        unchanged) — `reporting_manager_id` is a separate, unrestricted-
        by-role column introduced specifically for this chart.
        """

        result = await self.db.execute(
            select(User)
            .options(
                selectinload(User.role),
                selectinload(User.category),
                selectinload(User.categories),
            )
            .where(
                User.reporting_manager_id == user_id,
                User.is_active.is_(True),
            )
            .order_by(User.name)
        )

        return list(result.scalars().all())

    async def get_by_category(
        self,
        category_id: UUID,
    ) -> list[User]:

        result = await self.db.execute(
            select(User)
            .options(selectinload(User.role))
            .where(User.category_id == category_id, User.is_active.is_(True))
            .order_by(User.name)
        )

        return list(result.scalars().all())

    async def list_active_ids_by_categories(
        self,
        category_ids: list[UUID],
    ) -> set[UUID]:
        """
        Every active user in ANY of the given categories, via the
        many-to-many `user_categories` join (not the legacy singular
        `category_id` column) — a user tagged with one of these
        categories only through `categories`/`user_categories` is
        still included. Used by
        OrganizationService.get_reporting_scope_user_ids to widen the
        Users page's visibility scope by Reporting Manager category
        assignment.
        """

        if not category_ids:
            return set()

        result = await self.db.execute(
            select(User.user_id)
            .join(user_categories, user_categories.c.user_id == User.user_id)
            .where(
                user_categories.c.category_id.in_(category_ids),
                User.is_active.is_(True),
            )
            .distinct()
        )

        return set(result.scalars().all())

    async def replace_categories(
        self,
        user_id: UUID,
        category_ids: list[UUID],
        assigned_by: UUID | None = None,
    ) -> None:
        """
        Full-replace the `user_categories` row set for one user —
        deletes every existing row for them, then inserts the new set
        — in the same transaction/session as the caller's other User
        mutations (no separate commit here). Duplicate ids in
        `category_ids` are collapsed before insert. See
        UserService.set_user_categories, the sole caller.
        """

        await self.db.execute(
            delete(user_categories).where(user_categories.c.user_id == user_id)
        )

        deduped_ids = list(dict.fromkeys(category_ids))
        if deduped_ids:
            await self.db.execute(
                insert(user_categories),
                [
                    {
                        "user_id": user_id,
                        "category_id": category_id,
                        "assigned_by": assigned_by,
                    }
                    for category_id in deduped_ids
                ],
            )

    async def activate(
        self,
        user: User,
    ) -> User:

        user.is_active = True

        await self.db.flush()
        await self.db.refresh(user)

        return user

    async def deactivate(
        self,
        user: User,
    ) -> User:

        user.is_active = False

        await self.db.flush()
        await self.db.refresh(user)

        return user
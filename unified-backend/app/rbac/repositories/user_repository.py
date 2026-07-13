from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from shared_models.models import Role, User

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
        result = await self.db.execute(
            select(User)
            .options(joinedload(User.role), joinedload(User.category))
            .where(User.user_id == user_id)
        )

        return result.unique().scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User)
            .options(joinedload(User.role), joinedload(User.category))
            .where(User.email == email)
        )

        return result.unique().scalar_one_or_none()

    async def get_all(
        self,
        page: int = 1,
        page_size: int = 10,
        search: str | None = None,
        category_id: UUID | None = None,
    ) -> tuple[list[User], int]:
        """
        Returns:
            users,
            total_count
        """

        query = (
            select(User)
            .options(selectinload(User.role))
        )

        count_query = select(func.count()).select_from(User)

        if search:
            pattern = f"%{search}%"

            search_filter = or_(
                User.name.ilike(pattern),
                User.email.ilike(pattern),
            )

            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        if category_id is not None:
            query = query.where(User.category_id == category_id)
            count_query = count_query.where(User.category_id == category_id)

        total = (
            await self.db.execute(count_query)
        ).scalar_one()

        result = await self.db.execute(
            query
            .order_by(User.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        users = result.scalars().all()

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

        result = await self.db.execute(
            select(User)
            .options(selectinload(User.role))
            .where(User.role_id == role_id)
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
            .options(selectinload(User.role))
            .where(
                User.manager_id == manager_id,
                User.role_id == role_id,
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
            .options(selectinload(User.role))
            .where(User.teamlead_id == teamlead_id)
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
            .where(User.category_id == category_id)
            .order_by(User.name)
        )

        return list(result.scalars().all())

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
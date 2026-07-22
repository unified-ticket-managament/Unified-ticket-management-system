from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared_models.models import Role

from .base import BaseRepository


class RoleRepository(BaseRepository):
    """
    Repository for Role database operations.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    # --------------------------------------------------
    # Create
    # --------------------------------------------------

    async def create(self, role: Role) -> Role:
        self.db.add(role)
        await self.db.flush()
        await self.db.refresh(role)
        return role

    # --------------------------------------------------
    # Read
    # --------------------------------------------------

    async def get_by_id(self, role_id: UUID) -> Role | None:
        result = await self.db.execute(
            select(Role)
            .options(selectinload(Role.users))
            .where(Role.role_id == role_id)
        )

        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Role | None:
        result = await self.db.execute(
            select(Role)
            .where(Role.name == name)
        )

        return result.scalar_one_or_none()

    async def get_by_name_case_insensitive(self, name: str) -> Role | None:
        """
        Trim + case-insensitive lookup. `Role.name` has an exact-match unique
        index only, so " viewer"/"VIEWER"/"Viewer " are all distinct rows to
        Postgres despite being the same role to a human — this is what
        actually let a typo'd near-duplicate ("viewre" next to "Viewer")
        coexist as its own row. Used by create/update to reject this class of
        duplicate before it reaches the database, not to replace the DB's own
        exact-match unique index.
        """
        result = await self.db.execute(
            select(Role)
            .where(func.lower(Role.name) == name.strip().lower())
        )

        return result.scalar_one_or_none()

    async def get_all(
        self,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[Role], int]:

        count = (
            await self.db.execute(
                select(func.count()).select_from(Role)
            )
        ).scalar_one()

        result = await self.db.execute(
            select(Role)
            .options(selectinload(Role.users))
            .order_by(Role.name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        roles = result.scalars().all()

        return list(roles), count

    # --------------------------------------------------
    # Update
    # --------------------------------------------------

    async def update(self, role: Role) -> Role:
        await self.db.flush()
        await self.db.refresh(role)
        return role

    # --------------------------------------------------
    # Delete
    # --------------------------------------------------

    async def delete(self, role: Role) -> None:
        await self.db.delete(role)
        await self.db.flush()

    # --------------------------------------------------
    # Utility Methods
    # --------------------------------------------------

    async def exists(self, name: str) -> bool:
        result = await self.db.execute(
            select(Role.role_id)
            .where(Role.name == name)
        )

        return result.scalar_one_or_none() is not None

    async def get_users_count(
        self,
        role_id: UUID,
    ) -> int:

        result = await self.db.execute(
            select(func.count())
            .select_from(Role)
            .join(Role.users)
            .where(Role.role_id == role_id)
        )

        return result.scalar_one()
from uuid import UUID

from sqlalchemy import func, select

from app.models.permission import Permission

from .base import BaseRepository


class PermissionRepository(BaseRepository):
    """
    Repository for Permission database operations.
    """

    # --------------------------------------------------
    # Create
    # --------------------------------------------------

    async def create(
        self,
        permission: Permission,
    ) -> Permission:

        self.db.add(permission)
        await self.db.flush()
        await self.db.refresh(permission)

        return permission

    # --------------------------------------------------
    # Read
    # --------------------------------------------------

    async def get_by_id(
        self,
        permission_id: UUID,
    ) -> Permission | None:

        result = await self.db.execute(
            select(Permission).where(
                Permission.permission_id == permission_id
            )
        )

        return result.scalar_one_or_none()

    async def get_by_name(
        self,
        permission_name: str,
    ) -> Permission | None:

        result = await self.db.execute(
            select(Permission).where(
                Permission.permission_name == permission_name
            )
        )

        return result.scalar_one_or_none()

    async def get_all(
        self,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[Permission], int]:

        total = (
            await self.db.execute(
                select(func.count()).select_from(Permission)
            )
        ).scalar_one()

        result = await self.db.execute(
            select(Permission)
            .order_by(Permission.permission_name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        permissions = result.scalars().all()

        return list(permissions), total

    # --------------------------------------------------
    # Update
    # --------------------------------------------------

    async def update(
        self,
        permission: Permission,
    ) -> Permission:

        await self.db.flush()
        await self.db.refresh(permission)

        return permission

    # --------------------------------------------------
    # Delete
    # --------------------------------------------------

    async def delete(
        self,
        permission: Permission,
    ) -> None:

        await self.db.delete(permission)
        await self.db.flush()

    # --------------------------------------------------
    # Utility
    # --------------------------------------------------

    async def exists(
        self,
        permission_name: str,
    ) -> bool:

        result = await self.db.execute(
            select(Permission.permission_id).where(
                Permission.permission_name == permission_name
            )
        )

        return result.scalar_one_or_none() is not None
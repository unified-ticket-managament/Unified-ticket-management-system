from uuid import UUID

from sqlalchemy import delete, select

from app.rbac.models.permission import Permission
from app.rbac.models.role_permission import RolePermission


from .base import BaseRepository


class RolePermissionRepository(BaseRepository):
    """
    Repository for Role-Permission mapping.
    """

    async def assign_permission(
        self,
        role_id: UUID,
        permission_id: UUID,
    ) -> RolePermission:

        role_permission = RolePermission(
            role_id=role_id,
            permission_id=permission_id,
        )

        self.db.add(role_permission)

        await self.db.flush()
        await self.db.refresh(role_permission)

        return role_permission

    async def remove_permission(
        self,
        role_id: UUID,
        permission_id: UUID,
    ) -> None:

        await self.db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.permission_id == permission_id,
            )
        )

        await self.db.flush()

    async def get_permissions_by_role(
        self,
        role_id: UUID,
    ) -> list[Permission]:

        result = await self.db.execute(
            select(Permission)
            .join(
                RolePermission,
                Permission.permission_id
                == RolePermission.permission_id,
            )
            .where(RolePermission.role_id == role_id)
            .order_by(Permission.permission_name)
        )

        return list(result.scalars().all())

    async def remove_all_permissions(
        self,
        role_id: UUID,
    ) -> None:

        await self.db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id
            )
        )

        await self.db.flush()
from uuid import UUID

from fastapi import HTTPException, status

from app.rbac.models.permission import Permission
from app.rbac.repositories import PermissionRepository
from app.rbac.schemas.permission import PermissionCreate, PermissionUpdate


class PermissionService:
    """
    Business logic for Permission operations.
    """

    def __init__(
        self,
        permission_repository: PermissionRepository,
    ):
        self.permission_repository = permission_repository

    # --------------------------------------------------
    # Create Permission
    # --------------------------------------------------

    async def create_permission(
        self,
        permission_data: PermissionCreate,
    ) -> Permission:

        exists = await self.permission_repository.exists(
            permission_data.permission_name
        )

        if exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Permission already exists.",
            )

        permission = Permission(
            permission_name=permission_data.permission_name,
            description=permission_data.description,
        )

        return await self.permission_repository.create(permission)

    # --------------------------------------------------
    # Get Permission
    # --------------------------------------------------

    async def get_permission(
        self,
        permission_id: UUID,
    ) -> Permission:

        permission = await self.permission_repository.get_by_id(
            permission_id
        )

        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission not found.",
            )

        return permission

    async def get_permission_by_name(
        self,
        permission_name: str,
    ) -> Permission:

        permission = await self.permission_repository.get_by_name(
            permission_name
        )

        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission not found.",
            )

        return permission

    async def list_permissions(
        self,
        page: int = 1,
        page_size: int = 10,
    ):

        return await self.permission_repository.get_all(
            page,
            page_size,
        )

    # --------------------------------------------------
    # Update Permission
    # --------------------------------------------------

    async def update_permission(
        self,
        permission_id: UUID,
        permission_data: PermissionUpdate,
    ) -> Permission:

        permission = await self.get_permission(permission_id)

        update_data = permission_data.model_dump(
            exclude_unset=True
        )

        if "permission_name" in update_data:

            exists = await self.permission_repository.get_by_name(
                update_data["permission_name"]
            )

            if (
                exists
                and exists.permission_id != permission.permission_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Permission already exists.",
                )

        for field, value in update_data.items():
            setattr(permission, field, value)

        return await self.permission_repository.update(permission)

    # --------------------------------------------------
    # Delete Permission
    # --------------------------------------------------

    async def delete_permission(
        self,
        permission_id: UUID,
    ) -> None:

        permission = await self.get_permission(permission_id)

        await self.permission_repository.delete(permission)


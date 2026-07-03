from uuid import UUID

from fastapi import HTTPException, status

from app.repositories import (
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
)


class RolePermissionService:
    """
    Business logic for assigning permissions to roles.
    """

    def __init__(
        self,
        role_repository: RoleRepository,
        permission_repository: PermissionRepository,
        role_permission_repository: RolePermissionRepository,
    ):
        self.role_repository = role_repository
        self.permission_repository = permission_repository
        self.role_permission_repository = role_permission_repository

    # --------------------------------------------------
    # Assign Permission
    # --------------------------------------------------

    async def assign_permission(
        self,
        role_id: UUID,
        permission_id: UUID,
    ):

        role = await self.role_repository.get_by_id(role_id)

        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found.",
            )

        permission = await self.permission_repository.get_by_id(
            permission_id
        )

        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission not found.",
            )

        permissions = (
            await self.role_permission_repository.get_permissions_by_role(
                role_id
            )
        )

        if any(
            p.permission_id == permission_id
            for p in permissions
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Permission already assigned to this role.",
            )

        return await self.role_permission_repository.assign_permission(
            role_id,
            permission_id,
        )

    # --------------------------------------------------
    # Get Permissions of Role
    # --------------------------------------------------

    async def get_role_permissions(
        self,
        role_id: UUID,
    ):

        role = await self.role_repository.get_by_id(role_id)

        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found.",
            )

        return (
            await self.role_permission_repository.get_permissions_by_role(
                role_id
            )
        )

    # --------------------------------------------------
    # Remove Permission
    # --------------------------------------------------

    async def remove_permission(
        self,
        role_id: UUID,
        permission_id: UUID,
    ):

        role = await self.role_repository.get_by_id(role_id)

        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found.",
            )

        permission = await self.permission_repository.get_by_id(
            permission_id
        )

        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission not found.",
            )

        await self.role_permission_repository.remove_permission(
            role_id,
            permission_id,
        )

    # --------------------------------------------------
    # Replace Permissions
    # --------------------------------------------------

    async def replace_permissions(
        self,
        role_id: UUID,
        permission_ids: list[UUID],
    ):

        role = await self.role_repository.get_by_id(role_id)

        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found.",
            )

        await self.role_permission_repository.remove_all_permissions(
            role_id
        )

        for permission_id in permission_ids:

            permission = (
                await self.permission_repository.get_by_id(
                    permission_id
                )
            )

            if permission is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Permission {permission_id} not found.",
                )

            await self.role_permission_repository.assign_permission(
                role_id,
                permission_id,
            )
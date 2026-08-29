import json
from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import User

from app.rbac.models.permission import Permission
from app.rbac.repositories import (
    PermissionRepository,
    RolePermissionRepository,
    UserRepository,
)
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.schemas.permission import PermissionCreate, PermissionUpdate
from app.rbac.services.audit_log_service import AuditLogService


class PermissionService:
    """
    Business logic for Permission operations.
    """

    def __init__(
        self,
        permission_repository: PermissionRepository,
        role_permission_repository: RolePermissionRepository,
        user_repository: UserRepository,
        audit_log_service: AuditLogService,
    ):
        self.permission_repository = permission_repository
        self.role_permission_repository = role_permission_repository
        self.user_repository = user_repository
        self.audit_log_service = audit_log_service

    # --------------------------------------------------
    # Create Permission
    # --------------------------------------------------

    async def create_permission(
        self,
        permission_data: PermissionCreate,
        actor: User | None = None,
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

        permission = await self.permission_repository.create(permission)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="permission.create",
                entity_type="permission",
                entity_id=str(permission.permission_id),
                new_value=json.dumps(
                    {
                        "permission_name": permission.permission_name,
                        "description": permission.description,
                    }
                ),
            )
        )

        return permission

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
        actor: User | None = None,
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

        old_values = {field: getattr(permission, field) for field in update_data}

        for field, value in update_data.items():
            setattr(permission, field, value)

        permission = await self.permission_repository.update(permission)

        if update_data:
            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="permission.update",
                    entity_type="permission",
                    entity_id=str(permission.permission_id),
                    old_value=json.dumps(old_values),
                    new_value=json.dumps(update_data),
                )
            )

        return permission

    # --------------------------------------------------
    # Delete Permission
    # --------------------------------------------------

    async def delete_permission(
        self,
        permission_id: UUID,
        actor: User | None = None,
    ) -> None:

        permission = await self.get_permission(permission_id)
        old_values = {
            "permission_name": permission.permission_name,
            "description": permission.description,
        }

        # Every role currently holding this permission must be resolved
        # *before* the delete below — the join this depends on returns
        # nothing once the row is gone. Bumping permission_version for
        # each affected role's users (same bulk UPDATE
        # RolePermissionService.assign_permission/remove_permission/
        # replace_permissions already runs on any role-permission
        # change) closes the gap where a deleted permission would
        # otherwise remain live in an already-issued JWT/cached session
        # for the rest of that token's natural lifetime instead of the
        # usual RBAC-cache TTL window.
        affected_role_ids = (
            await self.role_permission_repository.get_role_ids_by_permission(
                permission_id
            )
        )

        await self.permission_repository.delete(permission)

        for role_id in affected_role_ids:
            await self.user_repository.bump_permission_version_for_role(
                role_id
            )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="permission.delete",
                entity_type="permission",
                entity_id=str(permission_id),
                old_value=json.dumps(old_values),
            )
        )


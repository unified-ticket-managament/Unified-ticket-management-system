import json
from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import User

from app.core.rbac_cache import get_rbac_cache
from app.rbac.repositories import (
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
)
from app.rbac.schemas.audit_log import AuditLogCreate
from app.rbac.services.access_control import (
    ensure_can_grant_role_permissions,
    ensure_can_manage_role_permissions,
)
from app.rbac.services.audit_log_service import AuditLogService


def _invalidate_stale_cache_entries(
    previous_versions: list[tuple],
) -> None:
    """
    Evicts each affected user's now-superseded (user_id, old_version)
    entry from rbac_cache right away, so an already-warm cache hit
    can't keep serving their pre-grant/pre-revoke permission set for
    the rest of its TTL window — see RBACCache.invalidate's own
    docstring for why this is the intended way to force an immediate
    re-check. Their next request simply misses the cache and falls
    through to the existing DB-verified path, which already handles
    a permission_version mismatch correctly (401, then the frontend's
    existing refresh-and-retry).
    """

    cache = get_rbac_cache()
    for user_id, old_version in previous_versions:
        cache.invalidate(str(user_id), old_version)


class RolePermissionService:
    """
    Business logic for assigning permissions to roles.
    """

    def __init__(
        self,
        role_repository: RoleRepository,
        permission_repository: PermissionRepository,
        role_permission_repository: RolePermissionRepository,
        user_repository: UserRepository,
        audit_log_service: AuditLogService,
    ):
        self.role_repository = role_repository
        self.permission_repository = permission_repository
        self.role_permission_repository = role_permission_repository
        self.user_repository = user_repository
        self.audit_log_service = audit_log_service

    # --------------------------------------------------
    # Assign Permission
    # --------------------------------------------------

    async def assign_permission(
        self,
        role_id: UUID,
        permission_id: UUID,
        actor: User | None = None,
    ):

        role = await self.role_repository.get_by_id(role_id)

        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found.",
            )

        if actor is not None:
            ensure_can_manage_role_permissions(actor, role)

        permission = await self.permission_repository.get_by_id(
            permission_id
        )

        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission not found.",
            )

        if actor is not None:
            ensure_can_grant_role_permissions(actor, [permission.permission_name])

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

        result = await self.role_permission_repository.assign_permission(
            role_id,
            permission_id,
        )

        # Every user holding this role now has a different effective
        # permission set — one bulk UPDATE (not a per-user loop, see
        # UserRepository.bump_permission_version_for_role) rejects any
        # of their already-issued sessions on next DB-verified request
        # instead of leaving them on the old, now-incomplete permission
        # list for the rest of that token's natural TTL.
        previous_versions = await self.user_repository.bump_permission_version_for_role(role_id)
        _invalidate_stale_cache_entries(previous_versions)
        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="role.permissions_added",
                entity_type="role",
                entity_id=str(role_id),
                new_value=json.dumps({"added": [permission.permission_name]}),
            )
        )

        return result

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
        actor: User | None = None,
    ):

        role = await self.role_repository.get_by_id(role_id)

        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found.",
            )

        if actor is not None:
            ensure_can_manage_role_permissions(actor, role)

        permission = await self.permission_repository.get_by_id(
            permission_id
        )

        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission not found.",
            )

        # Removal is deliberately never ownership-scoped (see
        # ensure_can_grant_role_permissions's own docstring) — no
        # matching check here, unlike assign_permission above.

        await self.role_permission_repository.remove_permission(
            role_id,
            permission_id,
        )

        # See the matching comment in assign_permission above.
        previous_versions = await self.user_repository.bump_permission_version_for_role(role_id)
        _invalidate_stale_cache_entries(previous_versions)
        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id if actor else None,
                action="role.permissions_removed",
                entity_type="role",
                entity_id=str(role_id),
                old_value=json.dumps({"removed": [permission.permission_name]}),
            )
        )

    # --------------------------------------------------
    # Replace Permissions
    # --------------------------------------------------

    async def replace_permissions(
        self,
        role_id: UUID,
        permission_ids: list[UUID],
        actor: User | None = None,
    ):

        role = await self.role_repository.get_by_id(role_id)

        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found.",
            )

        if actor is not None:
            ensure_can_manage_role_permissions(actor, role)

        previous_permissions = (
            await self.role_permission_repository.get_permissions_by_role(
                role_id
            )
        )
        previous_ids = {p.permission_id for p in previous_permissions}
        new_ids = set(permission_ids)

        # Resolved and ownership-checked *before* remove_all_permissions
        # runs below, so a rejected request leaves the DB untouched —
        # only the newly-added ids are ownership-scoped (see
        # ensure_can_grant_role_permissions), never ones the role
        # already had.
        newly_added_ids = new_ids - previous_ids

        if actor is not None and newly_added_ids:
            newly_added_permissions = []

            for permission_id in newly_added_ids:
                permission = await self.permission_repository.get_by_id(permission_id)

                if permission is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Permission {permission_id} not found.",
                    )

                newly_added_permissions.append(permission)

            ensure_can_grant_role_permissions(
                actor, [p.permission_name for p in newly_added_permissions]
            )

        await self.role_permission_repository.remove_all_permissions(
            role_id
        )

        assigned_permissions = []

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

            assigned_permissions.append(permission)

            await self.role_permission_repository.assign_permission(
                role_id,
                permission_id,
            )

        # See the matching comment in assign_permission above.
        previous_versions = await self.user_repository.bump_permission_version_for_role(role_id)
        _invalidate_stale_cache_entries(previous_versions)
        # Logged as up to two rows (added / removed) rather than one
        # combined "replace" row — matches the task's requirement that
        # "Permissions Added" and "Permissions Removed" are distinct,
        # filterable audit actions, and only fires for what actually
        # changed rather than re-logging the whole set on every save.
        added_names = [
            p.permission_name for p in assigned_permissions if p.permission_id not in previous_ids
        ]
        removed_names = [
            p.permission_name for p in previous_permissions if p.permission_id not in new_ids
        ]

        if added_names:
            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="role.permissions_added",
                    entity_type="role",
                    entity_id=str(role_id),
                    new_value=json.dumps({"added": added_names}),
                )
            )

        if removed_names:
            await self.audit_log_service.create_log(
                AuditLogCreate(
                    user_id=actor.user_id if actor else None,
                    action="role.permissions_removed",
                    entity_type="role",
                    entity_id=str(role_id),
                    old_value=json.dumps({"removed": removed_names}),
                )
            )

import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from shared_models.models import User

from app.models.permission_override import UserPermissionOverride
from app.repositories import (
    PermissionOverrideRepository,
    PermissionRepository,
    UserRepository,
)
from app.schemas.audit_log import AuditLogCreate
from app.schemas.permission_override import (
    GrantOverrideRequest,
    PermissionOverrideResponse,
)
from app.services.audit_log_service import AuditLogService
from app.services.organization_service import OrganizationService
from app.services.permission_resolver import PermissionResolverService

# Roles with unconditional authority to manage any user's permission
# overrides — matches seed.py's own design ("Site Lead: all
# permissions", Super Admin implicitly so).
UNRESTRICTED_OVERRIDE_ROLES = {"Super Admin", "Site Lead"}

# The one role whose override authority is scoped to their own
# reports rather than being global (see seed.py's DEFAULT_ROLES
# comment: Account Manager's override_grant/revoke is "for their own
# reports").
SCOPED_OVERRIDE_ROLE = "Account Manager"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PermissionOverrideService:
    """
    Business logic for granting/revoking a permission to one specific
    user, independent of their role's own bundle. See
    PermissionResolverService for how these are merged back in at
    read time.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        permission_repository: PermissionRepository,
        permission_override_repository: PermissionOverrideRepository,
        organization_service: OrganizationService,
        permission_resolver: PermissionResolverService,
        audit_log_service: AuditLogService,
    ):
        self.user_repository = user_repository
        self.permission_repository = permission_repository
        self.permission_override_repository = permission_override_repository
        self.organization_service = organization_service
        self.permission_resolver = permission_resolver
        self.audit_log_service = audit_log_service

    # --------------------------------------------------
    # Authorization
    # --------------------------------------------------

    async def _ensure_can_manage_overrides(
        self,
        actor: User,
        target: User,
    ) -> None:

        actor_permissions, _ = (
            await self.permission_resolver.get_effective_permissions(actor)
        )

        if "permission:override_grant" not in actor_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to manage permission overrides.",
            )

        if actor.role.name in UNRESTRICTED_OVERRIDE_ROLES:
            return

        if actor.role.name == SCOPED_OVERRIDE_ROLE:
            subordinate_ids = (
                await self.organization_service.get_subordinate_user_ids(actor)
            )

            if target.user_id not in subordinate_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only manage permission overrides for your own reports.",
                )

            return

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage permission overrides.",
        )

    # --------------------------------------------------
    # Grant
    # --------------------------------------------------

    async def grant(
        self,
        actor: User,
        target_user_id: UUID,
        request: GrantOverrideRequest,
    ) -> PermissionOverrideResponse:

        target = await self.user_repository.get_by_id(target_user_id)

        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        permission = await self.permission_repository.get_by_id(
            request.permission_id
        )

        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission not found.",
            )

        await self._ensure_can_manage_overrides(actor, target)

        role_permission_names, _ = (
            await self.permission_resolver.get_effective_permissions(target)
        )

        if permission.permission_name in role_permission_names:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This user's role already grants this permission; "
                    "an override would be redundant."
                ),
            )

        existing = (
            await self.permission_override_repository.get_active_by_user_and_permission(
                target_user_id,
                request.permission_id,
            )
        )

        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This permission is already granted to this user. "
                    "Revoke the existing grant first if you want to change "
                    "its expiry or reason."
                ),
            )

        override = UserPermissionOverride(
            user_id=target_user_id,
            permission_id=request.permission_id,
            granted_by=actor.user_id,
            reason=request.reason,
            expires_at=request.expires_at,
        )

        override = await self.permission_override_repository.create(override)

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id,
                action="permission_override.grant",
                entity_type="user_permission_override",
                entity_id=str(override.override_id),
                new_value=json.dumps(
                    {
                        "target_user_id": str(target.user_id),
                        "permission_name": permission.permission_name,
                        "expires_at": (
                            request.expires_at.isoformat()
                            if request.expires_at
                            else None
                        ),
                        "reason": request.reason,
                    }
                ),
            )
        )

        return self._to_response(override)

    # --------------------------------------------------
    # Revoke
    # --------------------------------------------------

    async def revoke(
        self,
        actor: User,
        target_user_id: UUID,
        override_id: UUID,
    ) -> None:

        target = await self.user_repository.get_by_id(target_user_id)

        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        override = await self.permission_override_repository.get_by_id(
            override_id
        )

        if override is None or override.user_id != target_user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Permission override not found.",
            )

        if override.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This permission override has already been revoked.",
            )

        await self._ensure_can_manage_overrides(actor, target)

        permission_name = override.permission.permission_name

        await self.permission_override_repository.revoke(
            override,
            revoked_by=actor.user_id,
        )

        await self.audit_log_service.create_log(
            AuditLogCreate(
                user_id=actor.user_id,
                action="permission_override.revoke",
                entity_type="user_permission_override",
                entity_id=str(override.override_id),
                old_value=json.dumps(
                    {
                        "target_user_id": str(target.user_id),
                        "permission_name": permission_name,
                    }
                ),
            )
        )

    # --------------------------------------------------
    # List
    # --------------------------------------------------

    async def list_for_user(
        self,
        actor: User,
        target_user_id: UUID,
        include_revoked: bool,
    ) -> list[PermissionOverrideResponse]:

        target = await self.user_repository.get_by_id(target_user_id)

        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )

        await self._ensure_can_manage_overrides(actor, target)

        overrides = await self.permission_override_repository.list_all_by_user(
            target_user_id,
            include_revoked=include_revoked,
        )

        return [self._to_response(o) for o in overrides]

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    @staticmethod
    def _to_response(
        override: UserPermissionOverride,
    ) -> PermissionOverrideResponse:

        is_active = override.revoked_at is None and (
            override.expires_at is None or override.expires_at > utc_now()
        )

        return PermissionOverrideResponse(
            override_id=override.override_id,
            user_id=override.user_id,
            permission_id=override.permission_id,
            permission_name=override.permission.permission_name,
            granted_by=override.granted_by,
            reason=override.reason,
            granted_at=override.granted_at,
            expires_at=override.expires_at,
            revoked_at=override.revoked_at,
            revoked_by=override.revoked_by,
            is_active=is_active,
        )

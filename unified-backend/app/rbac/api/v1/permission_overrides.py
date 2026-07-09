from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.rbac.repositories import (
    AuditLogRepository,
    PermissionOverrideRepository,
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
)
from app.rbac.schemas.permission_override import (
    GrantOverrideRequest,
    PermissionOverrideResponse,
)
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.organization_service import OrganizationService
from app.rbac.services.permission_override_service import PermissionOverrideService
from app.rbac.services.permission_resolver import PermissionResolverService

router = APIRouter(
    prefix="/users",
    tags=["Permission Overrides"],
)


# --------------------------------------------------
# Dependency
# --------------------------------------------------


def get_permission_override_service(
    db: AsyncSession = Depends(get_db),
) -> PermissionOverrideService:
    """
    Returns PermissionOverrideService instance.
    """

    role_permission_repository = RolePermissionRepository(db)
    permission_override_repository = PermissionOverrideRepository(db)

    permission_resolver = PermissionResolverService(
        role_permission_repository=role_permission_repository,
        permission_override_repository=permission_override_repository,
    )

    organization_service = OrganizationService(
        user_repository=UserRepository(db),
        role_repository=RoleRepository(db),
    )

    audit_log_service = AuditLogService(
        audit_log_repository=AuditLogRepository(db),
    )

    return PermissionOverrideService(
        user_repository=UserRepository(db),
        permission_repository=PermissionRepository(db),
        permission_override_repository=permission_override_repository,
        organization_service=organization_service,
        permission_resolver=permission_resolver,
        audit_log_service=audit_log_service,
    )


# --------------------------------------------------
# Grant Override
# --------------------------------------------------


@router.post(
    "/{user_id}/permission-overrides",
    response_model=PermissionOverrideResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant a personal permission override",
)
async def grant_permission_override(
    user_id: UUID,
    request: GrantOverrideRequest,
    service: PermissionOverrideService = Depends(get_permission_override_service),
    current_user=Depends(get_current_active_user),
):
    """
    Grants one specific permission to one specific user, independent
    of their role. Never changes what anyone else who shares that
    role can do.
    """

    return await service.grant(current_user, user_id, request)


# --------------------------------------------------
# List Overrides
# --------------------------------------------------


@router.get(
    "/{user_id}/permission-overrides",
    response_model=list[PermissionOverrideResponse],
    status_code=status.HTTP_200_OK,
    summary="List a user's personal permission overrides",
)
async def list_permission_overrides(
    user_id: UUID,
    include_revoked: bool = Query(False),
    service: PermissionOverrideService = Depends(get_permission_override_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns the personal permission grants for one user (active only,
    unless include_revoked is set).
    """

    return await service.list_for_user(
        current_user,
        user_id,
        include_revoked=include_revoked,
    )


# --------------------------------------------------
# Revoke Override
# --------------------------------------------------


@router.delete(
    "/{user_id}/permission-overrides/{override_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a personal permission override",
)
async def revoke_permission_override(
    user_id: UUID,
    override_id: UUID,
    service: PermissionOverrideService = Depends(get_permission_override_service),
    current_user=Depends(get_current_active_user),
):
    """
    Revokes a previously granted personal permission override.
    """

    await service.revoke(current_user, user_id, override_id)

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.rbac.repositories.permission_repository import PermissionRepository
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.permission import PermissionResponse
from app.rbac.schemas.role_permission import AssignPermissionsRequest
from app.rbac.services.role_permission_service import RolePermissionService

router = APIRouter(
    prefix="/roles",
    tags=["Role Permissions"],
)


# --------------------------------------------------
# Dependency
# --------------------------------------------------


def get_role_permission_service(
    db: AsyncSession = Depends(get_db),
) -> RolePermissionService:
    """
    Returns RolePermissionService instance.
    """

    return RolePermissionService(
        role_repository=RoleRepository(db),
        permission_repository=PermissionRepository(db),
        role_permission_repository=RolePermissionRepository(db),
        user_repository=UserRepository(db),
    )


# --------------------------------------------------
# Get Role Permissions
# --------------------------------------------------


@router.get(
    "/{role_id}/permissions",
    response_model=list[PermissionResponse],
    status_code=status.HTTP_200_OK,
    summary="Get Role Permissions",
)
async def get_role_permissions(
    role_id: UUID,
    service: RolePermissionService = Depends(get_role_permission_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns the permissions currently assigned to a role.
    """

    return await service.get_role_permissions(role_id)


# --------------------------------------------------
# Replace Role Permissions
# --------------------------------------------------


@router.put(
    "/{role_id}/permissions",
    response_model=list[PermissionResponse],
    status_code=status.HTTP_200_OK,
    summary="Assign Permissions to Role",
)
async def update_role_permissions(
    role_id: UUID,
    request: AssignPermissionsRequest,
    service: RolePermissionService = Depends(get_role_permission_service),
    current_user=Depends(get_current_active_user),
):
    """
    Replaces the full set of permissions assigned to a role.
    """

    await service.replace_permissions(
        role_id,
        request.permission_ids,
    )

    return await service.get_role_permissions(role_id)

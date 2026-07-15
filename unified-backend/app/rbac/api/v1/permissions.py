from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.rbac.repositories.permission_repository import PermissionRepository
from app.rbac.schemas.permission import (
    PermissionCreate,
    PermissionListResponse,
    PermissionResponse,
    PermissionUpdate,
)
from app.rbac.services.access_control import ensure_has_permission
from app.rbac.services.permission_service import PermissionService

router = APIRouter(
    prefix="/permissions",
    tags=["Permissions"],
)


# --------------------------------------------------
# Dependency
# --------------------------------------------------


def get_permission_service(
    db: AsyncSession = Depends(get_db),
) -> PermissionService:
    """
    Returns PermissionService instance.
    """

    permission_repository = PermissionRepository(db)

    return PermissionService(
        permission_repository=permission_repository,
    )


# --------------------------------------------------
# Create Permission
# --------------------------------------------------


@router.post(
    "",
    response_model=PermissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Permission",
)
async def create_permission(
    permission_data: PermissionCreate,
    service: PermissionService = Depends(get_permission_service),
    current_user=Depends(get_current_active_user),
):
    """
    Create a new permission.
    """

    return await service.create_permission(
        permission_data,
    )


# --------------------------------------------------
# List Permissions
# --------------------------------------------------


@router.get(
    "",
    response_model=PermissionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Permissions",
)
async def list_permissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    service: PermissionService = Depends(get_permission_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns paginated list of permissions.
    """

    ensure_has_permission(current_user, "permission:view")

    permissions, total = await service.list_permissions(
        page=page,
        page_size=page_size,
    )

    return PermissionListResponse(
        permissions=permissions,
        total=total,
    )


# --------------------------------------------------
# Get Permission
# --------------------------------------------------


@router.get(
    "/{permission_id}",
    response_model=PermissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Permission",
)
async def get_permission(
    permission_id: UUID,
    service: PermissionService = Depends(get_permission_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns permission details.
    """

    ensure_has_permission(current_user, "permission:view")

    return await service.get_permission(
        permission_id,
    )


# --------------------------------------------------
# Update Permission
# --------------------------------------------------


@router.put(
    "/{permission_id}",
    response_model=PermissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Permission",
)
async def update_permission(
    permission_id: UUID,
    permission_data: PermissionUpdate,
    service: PermissionService = Depends(get_permission_service),
    current_user=Depends(get_current_active_user),
):
    """
    Update permission.
    """

    return await service.update_permission(
        permission_id,
        permission_data,
    )


# --------------------------------------------------
# Delete Permission
# --------------------------------------------------


@router.delete(
    "/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Permission",
)
async def delete_permission(
    permission_id: UUID,
    service: PermissionService = Depends(get_permission_service),
    current_user=Depends(get_current_active_user),
):
    """
    Delete permission.
    """

    await service.delete_permission(
        permission_id,
    )
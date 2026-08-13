from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.role import (
    RoleCreate,
    RoleListResponse,
    RoleResponse,
    RoleUpdate,
)
from app.rbac.schemas.user import UserResponse
from app.rbac.services.access_control import (
    ensure_can_view_full_role_population,
    ensure_has_permission,
)
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.role_service import RoleService

# The client-facing role — never stored in `users` at all (see
# UserService.CLIENT_ROLE_NAME's own docstring). GET /roles/{id}/users
# returns an empty list for it rather than erroring, since Client
# membership is a legitimate question with a legitimate (empty, from
# this table's perspective) answer.
CLIENT_ROLE_NAME = "Client"

router = APIRouter(
    prefix="/roles",
    tags=["Roles"],
)


# --------------------------------------------------
# Dependency
# --------------------------------------------------


def get_role_service(
    db: AsyncSession = Depends(get_db),
) -> RoleService:
    """
    Returns RoleService instance.
    """

    role_repository = RoleRepository(db)
    audit_log_service = AuditLogService(
        audit_log_repository=AuditLogRepository(db),
    )

    return RoleService(
        role_repository=role_repository,
        audit_log_service=audit_log_service,
    )


# --------------------------------------------------
# Create Role
# --------------------------------------------------


@router.post(
    "",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Role",
)
async def create_role(
    role_data: RoleCreate,
    service: RoleService = Depends(get_role_service),
    current_user=Depends(get_current_active_user),
):
    """
    Create a new role.
    """

    ensure_has_permission(current_user, "role:create")

    return await service.create_role(role_data, actor=current_user)


# --------------------------------------------------
# List Roles
# --------------------------------------------------


@router.get(
    "",
    response_model=RoleListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Roles",
)
async def list_roles(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    service: RoleService = Depends(get_role_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns paginated list of roles.
    """

    ensure_has_permission(current_user, "role:view")

    roles, total = await service.list_roles(
        page=page,
        page_size=page_size,
    )

    return RoleListResponse(
        roles=roles,
        total=total,
    )


# --------------------------------------------------
# Get Role
# --------------------------------------------------


@router.get(
    "/{role_id}",
    response_model=RoleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Role",
)
async def get_role(
    role_id: UUID,
    service: RoleService = Depends(get_role_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns role details.
    """

    ensure_has_permission(current_user, "role:view")

    return await service.get_role(role_id)


# --------------------------------------------------
# List Users For Role (Roles page "Assigned Users"/counts only)
# --------------------------------------------------


@router.get(
    "/{role_id}/users",
    response_model=list[UserResponse],
    status_code=status.HTTP_200_OK,
    summary="List Users For Role",
)
async def list_users_for_role(
    role_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    """
    Every active user holding this role, company-wide — deliberately
    NOT hierarchy-scoped (unlike GET /users, which is scoped via
    UserService.list_users/OrganizationService.get_subordinate_user_ids
    for Account Manager/Team Lead). Backs the Roles page's "Assigned
    Users" panel and per-role counts only; every other consumer of
    hierarchy scoping (the Users page, the Organization Chart,
    permission-override grant/revoke authority) is untouched by this
    route and keeps reading from its own existing code path.
    """

    ensure_has_permission(current_user, "role:view")
    ensure_can_view_full_role_population(current_user)

    role = await RoleRepository(db).get_by_id(role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found.")

    if role.name == CLIENT_ROLE_NAME:
        return []

    return await UserRepository(db).get_by_role(role_id)


# --------------------------------------------------
# Update Role
# --------------------------------------------------


@router.put(
    "/{role_id}",
    response_model=RoleResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Role",
)
async def update_role(
    role_id: UUID,
    role_data: RoleUpdate,
    service: RoleService = Depends(get_role_service),
    current_user=Depends(get_current_active_user),
):
    """
    Update role.
    """

    ensure_has_permission(current_user, "role:update")

    return await service.update_role(
        role_id,
        role_data,
        actor=current_user,
    )


# --------------------------------------------------
# Delete Role
# --------------------------------------------------


@router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Role",
)
async def delete_role(
    role_id: UUID,
    service: RoleService = Depends(get_role_service),
    current_user=Depends(get_current_active_user),
):
    """
    Delete role.
    """

    ensure_has_permission(current_user, "role:delete")

    await service.delete_role(role_id, actor=current_user)
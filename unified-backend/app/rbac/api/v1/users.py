from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.category_repository import CategoryRepository
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.role_repository import RoleRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.organization import OrganizationNode
from app.rbac.schemas.user import (
    UserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)
from app.rbac.services.access_control import ensure_has_permission
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.organization_service import OrganizationService
from app.rbac.services.user_service import UserService
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.user_repository import UserRepository as TicketingUserRepository
from app.ticketing.services.client_service import ClientService

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


# --------------------------------------------------
# Dependency
# --------------------------------------------------


def get_user_service(
    db: AsyncSession = Depends(get_db),
) -> UserService:
    """
    Returns UserService instance.
    """

    user_repository = UserRepository(db)
    role_repository = RoleRepository(db)
    category_repository = CategoryRepository(db)
    audit_log_service = AuditLogService(
        audit_log_repository=AuditLogRepository(db),
    )
    client_repository = ClientRepository(db)
    client_service = ClientService(
        client_repository=client_repository,
        user_repository=TicketingUserRepository(db),
        category_repository=category_repository,
    )
    organization_service = OrganizationService(
        user_repository=user_repository,
        role_repository=role_repository,
        reporting_manager_repository=ReportingManagerRepository(db),
    )

    return UserService(
        user_repository=user_repository,
        role_repository=role_repository,
        category_repository=category_repository,
        audit_log_service=audit_log_service,
        client_repository=client_repository,
        client_service=client_service,
        organization_service=organization_service,
    )


def get_organization_service(
    db: AsyncSession = Depends(get_db),
) -> OrganizationService:
    """
    Returns OrganizationService instance.
    """

    return OrganizationService(
        user_repository=UserRepository(db),
        role_repository=RoleRepository(db),
        reporting_manager_repository=ReportingManagerRepository(db),
    )


# --------------------------------------------------
# Create User
# --------------------------------------------------


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create User",
)
async def create_user(
    user_data: UserCreate,
    service: UserService = Depends(get_user_service),
    current_user=Depends(get_current_active_user),
):
    """
    Create a new user.
    """

    ensure_has_permission(current_user, "user:create")

    return await service.create_user(user_data, actor=current_user)


# --------------------------------------------------
# List Users
# --------------------------------------------------


@router.get(
    "",
    response_model=UserListResponse,
    summary="List Users",
)
async def list_users(
    page: int = Query(
        default=1,
        ge=1,
    ),
    page_size: int = Query(
        default=10,
        ge=1,
        le=100,
    ),
    search: str | None = Query(
        default=None,
    ),
    category_id: UUID | None = Query(
        default=None,
        description="Filter to users belonging to this work-specialization category (legacy singular — see category_ids).",
    ),
    category_ids: list[UUID] | None = Query(
        default=None,
        description=(
            "Filter to users belonging to ANY of these work-specialization "
            "categories (repeat the param for multiple, e.g. "
            "?category_ids=a&category_ids=b) — a user matching more than one "
            "requested category still appears exactly once."
        ),
    ),
    include_reporting_scope: bool = Query(
        default=False,
        description=(
            "Widen the caller's visibility to include every user reachable "
            "through their own Reporting Manager category assignments, on "
            "top of their existing reporting-hierarchy scope. Used by the "
            "Users-management page only — every other caller keeps the "
            "narrower default."
        ),
    ),
    service: UserService = Depends(get_user_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns paginated list of users, optionally filtered by one or
    more categories (e.g. to find every Staff/Team Lead who works a
    given category).
    """

    ensure_has_permission(current_user, "user:view")

    users, total = await service.list_users(
        page=page,
        page_size=page_size,
        search=search,
        category_id=category_id,
        category_ids=category_ids,
        current_user=current_user,
        include_reporting_scope=include_reporting_scope,
    )

    return UserListResponse(
        users=users,
        total=total,
    )


# --------------------------------------------------
# Organization Chart
# --------------------------------------------------


@router.get(
    "/me/organization-chart",
    response_model=OrganizationNode,
    status_code=status.HTTP_200_OK,
    summary="Get Organization Chart",
)
async def get_organization_chart(
    service: OrganizationService = Depends(get_organization_service),
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the organization hierarchy chart centered on the
    currently authenticated user.

    Deliberately re-fetches a real, DB-backed User row rather than
    trusting `current_user` as-is: on an RBAC-cache hit (see
    app/dependencies/auth.py's `_build_transient_user`), `current_user`
    is a transient object reconstructed straight from JWT claims that
    only ever populates the handful of fields ticketing code reads
    (role, category, permissions, ...) — it never set
    `reporting_manager_id` at all, so every cache-hit request (i.e.
    most of them, after a session's first) saw it as `None` regardless
    of the real value, making the chart wrongly report "no reporting
    manager" for anyone whose session happened to be cache-warm. This
    is scoped to just this one route — the RBAC cache/JWT/transient-
    user reconstruction itself is untouched, still correct for every
    field it was actually built to carry.
    """

    real_user = await UserRepository(db).get_by_id(current_user.user_id)
    if real_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    return await service.get_chart_for_user(real_user)


# --------------------------------------------------
# Get User By ID
# --------------------------------------------------


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    summary="Get User",
)
async def get_user(
    user_id: UUID,
    service: UserService = Depends(get_user_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns a user by ID.
    """

    ensure_has_permission(current_user, "user:view")

    return await service.get_user(user_id)

# --------------------------------------------------
# Update User
# --------------------------------------------------


@router.put(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update User",
)
async def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    service: UserService = Depends(get_user_service),
    current_user=Depends(get_current_active_user),
):
    """
    Update an existing user.
    """

    ensure_has_permission(current_user, "user:update")

    return await service.update_user(
        user_id,
        user_data,
        actor=current_user,
    )


# --------------------------------------------------
# Delete User
# --------------------------------------------------


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete User",
)
async def delete_user(
    user_id: UUID,
    service: UserService = Depends(get_user_service),
    current_user=Depends(get_current_active_user),
):
    """
    Delete a user.
    """
    await service.delete_user(user_id, actor=current_user)


# --------------------------------------------------
# Activate User
# --------------------------------------------------


@router.patch(
    "/{user_id}/activate",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate User",
)
async def activate_user(
    user_id: UUID,
    service: UserService = Depends(get_user_service),
    current_user=Depends(get_current_active_user),
):
    """
    Activate a user account.
    """

    ensure_has_permission(current_user, "user:disable")

    return await service.activate_user(user_id, actor=current_user)


# --------------------------------------------------
# Deactivate User
# --------------------------------------------------


@router.patch(
    "/{user_id}/deactivate",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate User",
)
async def deactivate_user(
    user_id: UUID,
    service: UserService = Depends(get_user_service),
    current_user=Depends(get_current_active_user),
):
    """
    Deactivate a user account.
    """

    ensure_has_permission(current_user, "user:disable")

    return await service.deactivate_user(user_id, actor=current_user)
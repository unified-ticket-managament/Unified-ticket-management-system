from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.rbac.repositories import CategoryRepository, ReportingManagerRepository, UserRepository
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.schemas.category import (
    CategoryCreate,
    CategoryListResponse,
    CategoryMembersResponse,
    CategoryMembersUpdate,
    CategoryResponse,
    CategoryUpdate,
)
from app.rbac.services.access_control import ensure_has_permission
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.category_service import CategoryService
from app.ticketing.repositories.client_repository import ClientRepository

router = APIRouter(
    prefix="/categories",
    tags=["Categories"],
)


# --------------------------------------------------
# Dependency
# --------------------------------------------------


def get_category_service(
    db: AsyncSession = Depends(get_db),
) -> CategoryService:
    """
    Returns CategoryService instance.
    """

    category_repository = CategoryRepository(db)
    user_repository = UserRepository(db)
    client_repository = ClientRepository(db)
    reporting_manager_repository = ReportingManagerRepository(db)
    audit_log_service = AuditLogService(
        audit_log_repository=AuditLogRepository(db),
    )

    return CategoryService(
        category_repository=category_repository,
        user_repository=user_repository,
        reporting_manager_repository=reporting_manager_repository,
        audit_log_service=audit_log_service,
        client_repository=client_repository,
    )


# --------------------------------------------------
# Create Category
# --------------------------------------------------


@router.post(
    "",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Category",
)
async def create_category(
    category_data: CategoryCreate,
    service: CategoryService = Depends(get_category_service),
    current_user=Depends(get_current_active_user),
):
    """
    Create a new work-specialization category, optionally assigning
    Staff/Team Lead users to it at the same time.
    """

    ensure_has_permission(current_user, "category:create")

    return await service.create_category(category_data, actor=current_user)


# --------------------------------------------------
# List Categories
# --------------------------------------------------


@router.get(
    "",
    response_model=CategoryListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Categories",
)
async def list_categories(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=100),
    service: CategoryService = Depends(get_category_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns paginated list of categories — page_size defaults to 100
    since this is a small, mostly-static reference list, typically
    fetched in full to populate a dropdown.
    """

    categories, total = await service.list_categories(
        page=page,
        page_size=page_size,
    )

    return CategoryListResponse(
        categories=categories,
        total=total,
    )


# --------------------------------------------------
# Get Category
# --------------------------------------------------


@router.get(
    "/{category_id}",
    response_model=CategoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Category",
)
async def get_category(
    category_id: UUID,
    service: CategoryService = Depends(get_category_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns category details.
    """

    return await service.get_category(category_id)


# --------------------------------------------------
# Update Category
# --------------------------------------------------


@router.put(
    "/{category_id}",
    response_model=CategoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Category",
)
async def update_category(
    category_id: UUID,
    category_data: CategoryUpdate,
    service: CategoryService = Depends(get_category_service),
    current_user=Depends(get_current_active_user),
):
    """
    Update (rename) a category.
    """

    ensure_has_permission(current_user, "category:create")

    return await service.update_category(
        category_id,
        category_data,
        actor=current_user,
    )


# --------------------------------------------------
# Category Members (Edit Category — add/remove Team Leads/Staff)
# --------------------------------------------------


@router.get(
    "/{category_id}/members",
    response_model=CategoryMembersResponse,
    status_code=status.HTTP_200_OK,
    summary="List Category Members",
)
async def list_category_members(
    category_id: UUID,
    service: CategoryService = Depends(get_category_service),
    current_user=Depends(get_current_active_user),
):
    """
    Every user currently assigned to this category, with their real
    role name — backs the Edit Category UI's pre-populated Team
    Lead/Staff pickers. Viewing has no extra permission gate, matching
    every other read on this router.
    """

    members = await service.get_members(category_id)

    return CategoryMembersResponse(members=members)


@router.put(
    "/{category_id}/members",
    response_model=CategoryMembersResponse,
    status_code=status.HTTP_200_OK,
    summary="Set Category Members",
)
async def set_category_members(
    category_id: UUID,
    members_data: CategoryMembersUpdate,
    service: CategoryService = Depends(get_category_service),
    current_user=Depends(get_current_active_user),
):
    """
    Full-replace this category's Team Lead/Staff membership — adds
    whoever's newly listed, removes whoever's missing.
    """

    ensure_has_permission(current_user, "category:create")

    members = await service.set_members(
        category_id, members_data.user_ids, actor=current_user
    )

    return CategoryMembersResponse(members=members)


# --------------------------------------------------
# Delete Category
# --------------------------------------------------


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Category",
)
async def delete_category(
    category_id: UUID,
    service: CategoryService = Depends(get_category_service),
    current_user=Depends(get_current_active_user),
):
    """
    Delete category.
    """

    ensure_has_permission(current_user, "category:create")

    await service.delete_category(category_id, actor=current_user)

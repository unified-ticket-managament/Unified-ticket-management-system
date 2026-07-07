from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.repositories.category_repository import CategoryRepository
from app.schemas.category import (
    CategoryCreate,
    CategoryListResponse,
    CategoryResponse,
    CategoryUpdate,
)
from app.services.category_service import CategoryService

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

    return CategoryService(
        category_repository=category_repository,
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
    Create a new work-specialization category.
    """

    return await service.create_category(category_data)


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
    Update category.
    """

    return await service.update_category(
        category_id,
        category_data,
    )


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

    await service.delete_category(category_id)

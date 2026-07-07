from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import Category

from app.repositories import CategoryRepository
from app.schemas.category import CategoryCreate, CategoryUpdate


class CategoryService:
    """
    Business logic for Category operations — the fixed set of
    work-specialization categories Staff/Team Lead users belong to.
    """

    def __init__(
        self,
        category_repository: CategoryRepository,
    ):
        self.category_repository = category_repository

    # --------------------------------------------------
    # Create Category
    # --------------------------------------------------

    async def create_category(
        self,
        category_data: CategoryCreate,
    ) -> Category:

        exists = await self.category_repository.exists(
            category_data.category_name
        )

        if exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category already exists.",
            )

        category = Category(
            category_name=category_data.category_name,
        )

        return await self.category_repository.create(category)

    # --------------------------------------------------
    # Get Category
    # --------------------------------------------------

    async def get_category(
        self,
        category_id: UUID,
    ) -> Category:

        category = await self.category_repository.get_by_id(
            category_id
        )

        if category is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found.",
            )

        return category

    async def list_categories(
        self,
        page: int = 1,
        page_size: int = 10,
    ):
        return await self.category_repository.get_all(
            page,
            page_size,
        )

    # --------------------------------------------------
    # Update Category
    # --------------------------------------------------

    async def update_category(
        self,
        category_id: UUID,
        category_data: CategoryUpdate,
    ) -> Category:

        category = await self.get_category(category_id)

        update_data = category_data.model_dump(
            exclude_unset=True
        )

        if "category_name" in update_data:

            exists = await self.category_repository.get_by_name(
                update_data["category_name"]
            )

            if (
                exists
                and exists.category_id != category.category_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Category already exists.",
                )

        for field, value in update_data.items():
            setattr(category, field, value)

        return await self.category_repository.update(category)

    # --------------------------------------------------
    # Delete Category
    # --------------------------------------------------

    async def delete_category(
        self,
        category_id: UUID,
    ):

        category = await self.get_category(category_id)

        user_count = await self.category_repository.get_users_count(
            category.category_id
        )

        if user_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category cannot be deleted because it is assigned to users.",
            )

        await self.category_repository.delete(category)

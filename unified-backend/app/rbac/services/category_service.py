from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import Category, User

from app.rbac.repositories import CategoryRepository, UserRepository
from app.rbac.schemas.category import (
    CategoryCreate,
    CategoryMemberResponse,
    CategoryUpdate,
)


class CategoryService:
    """
    Business logic for Category operations — a work-specialization
    category is created dynamically at runtime (no fixed enum backing
    it — see shared_models.models.Category), optionally with Staff/
    Team Lead users assigned to it at creation time.
    """

    def __init__(
        self,
        category_repository: CategoryRepository,
        user_repository: UserRepository,
    ):
        self.category_repository = category_repository
        self.user_repository = user_repository

    # --------------------------------------------------
    # Create Category
    # --------------------------------------------------

    async def create_category(
        self,
        category_data: CategoryCreate,
        actor: User | None = None,
    ) -> Category:

        name = category_data.category_name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category name is required.",
            )

        exists = await self.category_repository.exists(name)

        if exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category already exists.",
            )

        # Assigning users is optional — an empty/omitted user_ids is a
        # normal, valid case (a category with zero members). Ids that
        # ARE submitted must resolve to real users, never trusted
        # blindly from the frontend.
        user_ids = list(dict.fromkeys(category_data.user_ids))
        if user_ids:
            found_users = await self.user_repository.get_by_ids(user_ids)
            if len(found_users) != len(user_ids):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="One or more users were not found.",
                )

        category = Category(category_name=name)
        category = await self.category_repository.create(category)

        await self.user_repository.add_users_to_category(
            category.category_id,
            user_ids,
            assigned_by=actor.user_id if actor else None,
        )

        category.assigned_user_count = len(user_ids)
        return category

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

        category.assigned_user_count = await self.category_repository.get_users_count(
            category.category_id
        )

        return category

    async def list_categories(
        self,
        page: int = 1,
        page_size: int = 10,
    ):
        categories, total = await self.category_repository.get_all(
            page,
            page_size,
        )

        counts = await self.category_repository.get_counts_by_category_ids(
            [category.category_id for category in categories]
        )
        for category in categories:
            category.assigned_user_count = counts.get(category.category_id, 0)

        return categories, total

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
            name = (update_data["category_name"] or "").strip()
            if not name:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Category name is required.",
                )

            exists = await self.category_repository.get_by_name(name)

            if (
                exists
                and exists.category_id != category.category_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Category already exists.",
                )

            update_data["category_name"] = name

        for field, value in update_data.items():
            setattr(category, field, value)

        # category.assigned_user_count was already computed by the
        # get_category() call above — membership isn't touched by a
        # rename, so it's still accurate; no need to re-query.
        assigned_user_count = category.assigned_user_count
        updated = await self.category_repository.update(category)
        updated.assigned_user_count = assigned_user_count
        return updated

    # --------------------------------------------------
    # Category Members (Edit Category — add/remove Team Leads/Staff)
    # --------------------------------------------------

    async def get_members(
        self,
        category_id: UUID,
    ) -> list[CategoryMemberResponse]:

        # 404s if the category doesn't exist, same as every other
        # category_id-taking method here.
        await self.get_category(category_id)

        rows = await self.category_repository.get_members(category_id)

        return [
            CategoryMemberResponse(
                user_id=user_id, name=name, email=email, role_name=role_name
            )
            for user_id, name, email, role_name in rows
        ]

    async def set_members(
        self,
        category_id: UUID,
        user_ids: list[UUID],
    ) -> list[CategoryMemberResponse]:
        """
        Full-replace this category's membership set — diffs the
        submitted `user_ids` against who's currently assigned and
        adds/removes only the difference, mirroring
        UserService.set_user_categories's own full-replace semantics
        but scoped to one category instead of one user. Submitted ids
        are validated to exist first, same as create_category.
        """

        await self.get_category(category_id)

        new_ids = set(dict.fromkeys(user_ids))
        if new_ids:
            found_users = await self.user_repository.get_by_ids(list(new_ids))
            if len(found_users) != len(new_ids):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="One or more users were not found.",
                )

        current_rows = await self.category_repository.get_members(category_id)
        current_ids = {user_id for user_id, _, _, _ in current_rows}

        to_add = list(new_ids - current_ids)
        to_remove = list(current_ids - new_ids)

        if to_add:
            await self.user_repository.add_users_to_category(category_id, to_add)
        if to_remove:
            await self.user_repository.remove_users_from_category(
                category_id, to_remove
            )

        return await self.get_members(category_id)

    # --------------------------------------------------
    # Delete Category
    # --------------------------------------------------

    async def delete_category(
        self,
        category_id: UUID,
    ):

        category = await self.get_category(category_id)

        # get_category() above already computed this.
        user_count = category.assigned_user_count

        if user_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category cannot be deleted because it is assigned to users.",
            )

        await self.category_repository.delete(category)

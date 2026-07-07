from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared_models.models import Category, User

from .base import BaseRepository


class CategoryRepository(BaseRepository):
    """
    Repository for Category database operations.
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    # --------------------------------------------------
    # Create
    # --------------------------------------------------

    async def create(self, category: Category) -> Category:
        self.db.add(category)
        await self.db.flush()
        await self.db.refresh(category)
        return category

    # --------------------------------------------------
    # Read
    # --------------------------------------------------

    async def get_by_id(self, category_id: UUID) -> Category | None:
        result = await self.db.execute(
            select(Category).where(Category.category_id == category_id)
        )

        return result.scalar_one_or_none()

    async def get_by_name(self, category_name: str) -> Category | None:
        result = await self.db.execute(
            select(Category).where(Category.category_name == category_name)
        )

        return result.scalar_one_or_none()

    async def get_all(
        self,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[Category], int]:

        count = (
            await self.db.execute(
                select(func.count()).select_from(Category)
            )
        ).scalar_one()

        result = await self.db.execute(
            select(Category)
            .order_by(Category.category_name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        categories = result.scalars().all()

        return list(categories), count

    # --------------------------------------------------
    # Update
    # --------------------------------------------------

    async def update(self, category: Category) -> Category:
        await self.db.flush()
        await self.db.refresh(category)
        return category

    # --------------------------------------------------
    # Delete
    # --------------------------------------------------

    async def delete(self, category: Category) -> None:
        await self.db.delete(category)
        await self.db.flush()

    # --------------------------------------------------
    # Utility Methods
    # --------------------------------------------------

    async def exists(self, category_name: str) -> bool:
        result = await self.db.execute(
            select(Category.category_id).where(Category.category_name == category_name)
        )

        return result.scalar_one_or_none() is not None

    async def get_users_count(self, category_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(User)
            .where(User.category_id == category_id)
        )

        return result.scalar_one()

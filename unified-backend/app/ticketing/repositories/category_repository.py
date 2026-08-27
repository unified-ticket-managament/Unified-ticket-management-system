# category_repository.py

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import Category


class CategoryRepository:
    """
    Read-only access to the shared `categories` table (owned by the
    RBAC service, not this backend — see shared_models.models.Category).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self, category_ids: list[UUID] | None = None) -> list[Category]:
        stmt = select(Category).order_by(Category.category_name)
        if category_ids is not None:
            stmt = stmt.where(Category.category_id.in_(category_ids))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, category_id: UUID) -> Category | None:
        result = await self.db.execute(
            select(Category).where(Category.category_id == category_id)
        )
        return result.scalar_one_or_none()

    async def exists(self, category_name: str) -> bool:
        """
        Real DB existence check for a category name — replaces the
        old compile-time `CategoryName` enum membership check that
        used to gate InteractionService.transfer_agent's destination-
        category validation (categories are created dynamically at
        runtime now, so a fixed Python allowlist can no longer answer
        this question).
        """

        result = await self.db.execute(
            select(Category.category_id).where(Category.category_name == category_name)
        )
        return result.scalar_one_or_none() is not None

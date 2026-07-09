# category_repository.py

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

    async def list_all(self) -> list[Category]:
        result = await self.db.execute(
            select(Category).order_by(Category.category_name)
        )
        return list(result.scalars().all())

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import Category, Role, User
from shared_models.models.user_category import user_categories

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
        # Case-insensitive — "AR"/"ar"/"Ar" must resolve to the same
        # row, matching this codebase's existing email-comparison
        # convention (func.lower(User.email) == email.lower()).
        result = await self.db.execute(
            select(Category).where(
                func.lower(Category.category_name) == category_name.lower()
            )
        )

        return result.scalar_one_or_none()

    async def get_by_ids(self, category_ids: list[UUID]) -> list[Category]:
        """
        Batch lookup backing UserService.set_user_categories's
        existence validation for a submitted `category_ids` list — one
        round trip regardless of how many ids are passed.
        """

        if not category_ids:
            return []

        result = await self.db.execute(
            select(Category).where(Category.category_id.in_(category_ids))
        )

        return list(result.scalars().all())

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

    async def get_active_by_inbox_email(self, inbox_email: str) -> Category | None:
        """
        Resolves a CATEGORY shared mailbox by its address — the
        category-mailbox counterpart to
        ClientRepository.get_active_by_inbox_email. Category has no
        is_active flag (unlike Client), so "active" here just means
        "exists with this address"; the method is named to match its
        Client sibling for callers (email_service.py) that treat both
        lookups uniformly.
        """

        result = await self.db.execute(
            select(Category).where(
                func.lower(Category.inbox_email) == inbox_email.lower()
            )
        )

        return result.scalar_one_or_none()

    async def list_active_inbox_emails(self) -> list[str]:
        """
        Every non-null inbox_email among categories — the category-
        mailbox candidate set the Graph poller unions in alongside
        Client.list_active_inbox_emails (see
        graph_mail_poller._resolve_mailboxes_to_poll).
        """

        result = await self.db.execute(
            select(Category.inbox_email).where(Category.inbox_email.isnot(None))
        )

        return [row[0] for row in result.all()]

    async def exists(self, category_name: str) -> bool:
        # Case-insensitive, same reasoning as get_by_name above.
        result = await self.db.execute(
            select(Category.category_id).where(
                func.lower(Category.category_name) == category_name.lower()
            )
        )

        return result.scalar_one_or_none() is not None

    async def get_users_count(self, category_id: UUID) -> int:
        """
        Counts real user_categories membership, not just the legacy
        scalar User.category_id — a user whose *primary* category
        differs from one they're also multi-assigned to (via the
        Work Categories multi-select) would otherwise be missed here,
        which could let deletion of an in-use category slip past the
        caller's "cannot delete, still has users" guard.
        """

        result = await self.db.execute(
            select(func.count(user_categories.c.user_id)).where(
                user_categories.c.category_id == category_id
            )
        )

        return result.scalar_one()

    async def get_counts_by_category_ids(
        self, category_ids: list[UUID]
    ) -> dict[UUID, int]:
        """
        Batch version of get_users_count — one grouped query for
        however many categories are being listed, not one query per
        row. Backs the Category Management UI's "Assigned Users"
        column. A category with zero members simply has no key here;
        callers should default missing entries to 0.
        """

        if not category_ids:
            return {}

        result = await self.db.execute(
            select(
                user_categories.c.category_id,
                func.count(user_categories.c.user_id),
            )
            .where(user_categories.c.category_id.in_(category_ids))
            .group_by(user_categories.c.category_id)
        )

        return dict(result.all())

    async def get_members(
        self, category_id: UUID
    ) -> list[tuple[UUID, str, str, str]]:
        """
        Every user currently holding this category via user_categories
        — one JOIN, no N+1 — returned as (user_id, name, email,
        role_name) tuples so the caller (the Edit Category UI) can
        bucket them into Team Lead/Staff without a second round trip.
        """

        result = await self.db.execute(
            select(User.user_id, User.name, User.email, Role.name)
            .join(user_categories, user_categories.c.user_id == User.user_id)
            .join(Role, Role.role_id == User.role_id)
            .where(user_categories.c.category_id == category_id)
            .order_by(User.name)
        )

        return list(result.all())

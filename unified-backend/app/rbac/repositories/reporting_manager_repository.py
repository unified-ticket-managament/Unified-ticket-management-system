from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared_models.models import Category, User

from app.rbac.models.reporting_manager_team import ReportingManagerTeam

from .base import BaseRepository

# No ORM relationship is declared from ReportingManagerTeam to User/
# Category (same convention as PermissionRequest — see that model's
# own docstring/repository) since the same `users` table is joined
# twice here (account_manager_id and assigned_by both point at it),
# which is simplest to express as a plain query-time join rather than
# a mapped relationship on either side.
_AssignedByUser = aliased(User)


class ReportingManagerRepository(BaseRepository):
    """
    Repository for ReportingManagerTeam — the Account Manager <->
    Category "Reporting Manager" mapping (see the model's own
    docstring for what this represents and why it's kept separate from
    `User.manager_id`/ticket-assignment capability).
    """

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    def _select_with_names(self):
        return (
            select(
                ReportingManagerTeam,
                User.name.label("account_manager_name"),
                Category.category_name.label("category_name"),
                _AssignedByUser.name.label("assigned_by_name"),
            )
            .join(User, User.user_id == ReportingManagerTeam.account_manager_id)
            .join(Category, Category.category_id == ReportingManagerTeam.category_id)
            .outerjoin(
                _AssignedByUser,
                _AssignedByUser.user_id == ReportingManagerTeam.assigned_by,
            )
        )

    async def create(self, mapping: ReportingManagerTeam) -> ReportingManagerTeam:
        self.db.add(mapping)
        await self.db.flush()
        await self.db.refresh(mapping)
        return mapping

    async def get_by_id(self, mapping_id: UUID):
        result = await self.db.execute(
            self._select_with_names().where(ReportingManagerTeam.id == mapping_id)
        )
        return result.one_or_none()

    async def exists(self, account_manager_id: UUID, category_id: UUID) -> bool:
        result = await self.db.execute(
            select(ReportingManagerTeam.id).where(
                ReportingManagerTeam.account_manager_id == account_manager_id,
                ReportingManagerTeam.category_id == category_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_all(self):
        result = await self.db.execute(
            self._select_with_names().order_by(
                User.name, Category.category_name
            )
        )
        return result.all()

    async def list_by_account_manager(self, account_manager_id: UUID):
        result = await self.db.execute(
            self._select_with_names()
            .where(ReportingManagerTeam.account_manager_id == account_manager_id)
            .order_by(Category.category_name)
        )
        return result.all()

    async def list_category_ids_by_account_manager(
        self, account_manager_id: UUID
    ) -> list[UUID]:
        """
        Just the category_ids a given Account Manager is Reporting
        Manager for — no name joins, used by the HR-style scoping
        checks (not the admin CRUD screen), which only ever need the
        raw ids.
        """

        result = await self.db.execute(
            select(ReportingManagerTeam.category_id).where(
                ReportingManagerTeam.account_manager_id == account_manager_id
            )
        )
        return list(result.scalars().all())

    async def list_account_manager_ids_by_category(
        self, category_id: UUID
    ) -> list[UUID]:
        result = await self.db.execute(
            select(ReportingManagerTeam.account_manager_id).where(
                ReportingManagerTeam.category_id == category_id
            )
        )
        return list(result.scalars().all())

    async def delete(self, mapping: ReportingManagerTeam) -> None:
        await self.db.delete(mapping)
        await self.db.flush()

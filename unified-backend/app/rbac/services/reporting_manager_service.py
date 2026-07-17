from uuid import UUID

from fastapi import HTTPException, status

from shared_models.models import User

from app.rbac.models.reporting_manager_team import ReportingManagerTeam
from app.rbac.repositories import CategoryRepository, ReportingManagerRepository, UserRepository
from app.rbac.schemas.reporting_manager import ReportingManagerAssign, ReportingManagerResponse

ACCOUNT_MANAGER_ROLE_NAME = "Account Manager"


def _to_response(row) -> ReportingManagerResponse:
    mapping: ReportingManagerTeam = row[0]

    return ReportingManagerResponse(
        id=mapping.id,
        account_manager_id=mapping.account_manager_id,
        account_manager_name=row.account_manager_name,
        category_id=mapping.category_id,
        category_name=row.category_name.value,
        assigned_by=mapping.assigned_by,
        assigned_by_name=row.assigned_by_name,
        assigned_at=mapping.assigned_at,
    )


class ReportingManagerService:
    """
    Business logic for the "Reporting Manager" mapping — an additional
    HR/people-management responsibility layered onto an existing
    Account Manager, scoped to one or more business categories (see
    ReportingManagerTeam's own docstring, and root CLAUDE.md's
    "Organization Structure" section for the full business rule this
    implements). Deliberately does not touch `User.manager_id`/
    `teamlead_id` or ticket-assignment scope — those stay exactly as
    they already are.
    """

    def __init__(
        self,
        reporting_manager_repository: ReportingManagerRepository,
        user_repository: UserRepository,
        category_repository: CategoryRepository,
    ):
        self.reporting_manager_repository = reporting_manager_repository
        self.user_repository = user_repository
        self.category_repository = category_repository

    async def assign(
        self,
        data: ReportingManagerAssign,
        actor: User | None = None,
    ) -> ReportingManagerResponse:

        account_manager = await self.user_repository.get_by_id(data.account_manager_id)

        if account_manager is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Account Manager not found.",
            )

        if account_manager.role.name != ACCOUNT_MANAGER_ROLE_NAME:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reporting Manager responsibility can only be assigned to a user holding the Account Manager role.",
            )

        category = await self.category_repository.get_by_id(data.category_id)

        if category is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found.",
            )

        if await self.reporting_manager_repository.exists(
            data.account_manager_id, data.category_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This Account Manager is already the Reporting Manager for this category.",
            )

        mapping = ReportingManagerTeam(
            account_manager_id=data.account_manager_id,
            category_id=data.category_id,
            assigned_by=actor.user_id if actor else None,
        )

        mapping = await self.reporting_manager_repository.create(mapping)

        row = await self.reporting_manager_repository.get_by_id(mapping.id)
        return _to_response(row)

    async def list_all(self) -> list[ReportingManagerResponse]:
        rows = await self.reporting_manager_repository.list_all()
        return [_to_response(row) for row in rows]

    async def list_by_account_manager(
        self, account_manager_id: UUID
    ) -> list[ReportingManagerResponse]:
        rows = await self.reporting_manager_repository.list_by_account_manager(
            account_manager_id
        )
        return [_to_response(row) for row in rows]

    async def revoke(self, mapping_id: UUID) -> None:
        row = await self.reporting_manager_repository.get_by_id(mapping_id)

        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reporting Manager assignment not found.",
            )

        await self.reporting_manager_repository.delete(row[0])

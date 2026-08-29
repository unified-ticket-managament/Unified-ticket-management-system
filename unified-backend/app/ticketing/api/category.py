from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_user
from app.ticketing.repositories.category_repository import CategoryRepository
from app.ticketing.schemas.category import CategoryResponse
from app.ticketing.services.access_control import ACCOUNT_MANAGER_ROLE_NAME

router = APIRouter(
    prefix="/categories",
    tags=["Categories"],
)


@router.get(
    "",
    response_model=list[CategoryResponse],
)
async def list_categories(
    mine: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Every work-specialization category — populates the ticket-creation
    category dropdown in the Account Manager's inbox, and (merged with
    Client rows client-side) the "All Clients" filter dropdown across
    Tickets/Interactions/Audit Log/Mail.

    `?mine=true` narrows the list to the categories the calling Account
    Manager is Reporting Manager for (via reporting_manager_teams) — a
    no-op for every other role. Omitting it (every caller that predates
    this flag — the Roles page roster, the Rules engine picker) is
    byte-identical to the old unconditional behavior.

    The Reporting Manager mapping is an optional, additive HR layer
    (see root CLAUDE.md's "Organization Structure") — most Account
    Managers have no rows in reporting_manager_teams at all. For those,
    `mine=true` falls back to the full unscoped list instead of an
    empty one, since "no HR override configured" should mean default
    full visibility, not zero categories.
    """

    category_ids: list[UUID] | None = None
    if mine and current_user.role.name == ACCOUNT_MANAGER_ROLE_NAME:
        from app.rbac.repositories.reporting_manager_repository import (
            ReportingManagerRepository,
        )

        reporting_manager_repository = ReportingManagerRepository(db)
        mapped_category_ids = await reporting_manager_repository.list_category_ids_by_account_manager(
            current_user.user_id
        )
        if mapped_category_ids:
            category_ids = mapped_category_ids

    repository = CategoryRepository(db)

    return await repository.list_all(category_ids=category_ids)

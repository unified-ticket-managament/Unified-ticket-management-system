from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.rbac.repositories.category_repository import CategoryRepository
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.reporting_manager import (
    ReportingManagerAssign,
    ReportingManagerListResponse,
    ReportingManagerResponse,
)
from app.rbac.services.access_control import ensure_has_permission
from app.rbac.services.reporting_manager_service import ReportingManagerService

router = APIRouter(
    prefix="/reporting-managers",
    tags=["Reporting Managers"],
)


def get_reporting_manager_service(
    db: AsyncSession = Depends(get_db),
) -> ReportingManagerService:
    return ReportingManagerService(
        reporting_manager_repository=ReportingManagerRepository(db),
        user_repository=UserRepository(db),
        category_repository=CategoryRepository(db),
    )


@router.post(
    "",
    response_model=ReportingManagerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign Reporting Manager",
)
async def assign_reporting_manager(
    data: ReportingManagerAssign,
    service: ReportingManagerService = Depends(get_reporting_manager_service),
    current_user=Depends(get_current_active_user),
):
    """
    Assigns an Account Manager as the Reporting Manager for a business
    category — an additional HR/people-management responsibility, not
    a role change (see root CLAUDE.md's "Organization Structure"
    section). Genuinely many-to-many: an Account Manager can hold this
    for several categories, and nothing stops a category from having
    more than one Reporting Manager either.
    """

    ensure_has_permission(current_user, "org:manage_reporting_managers")

    return await service.assign(data, actor=current_user)


@router.get(
    "",
    response_model=ReportingManagerListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Reporting Manager Assignments",
)
async def list_reporting_managers(
    account_manager_id: UUID | None = None,
    service: ReportingManagerService = Depends(get_reporting_manager_service),
    current_user=Depends(get_current_active_user),
):
    """
    Every Reporting Manager <-> category assignment, optionally
    filtered to one Account Manager.
    """

    ensure_has_permission(current_user, "org:manage_reporting_managers")

    items = (
        await service.list_by_account_manager(account_manager_id)
        if account_manager_id is not None
        else await service.list_all()
    )

    return ReportingManagerListResponse(items=items)


@router.delete(
    "/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke Reporting Manager Assignment",
)
async def revoke_reporting_manager(
    mapping_id: UUID,
    service: ReportingManagerService = Depends(get_reporting_manager_service),
    current_user=Depends(get_current_active_user),
):
    """
    Revokes one Account Manager <-> category Reporting Manager
    assignment. Does not touch the Account Manager's role, their own
    clients, or any Team Lead/Staff reporting line — only this one HR
    responsibility mapping.
    """

    ensure_has_permission(current_user, "org:manage_reporting_managers")

    await service.revoke(mapping_id)

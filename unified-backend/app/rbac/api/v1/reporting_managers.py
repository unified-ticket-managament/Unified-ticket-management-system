from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.repositories.category_repository import CategoryRepository
from app.rbac.repositories.reporting_manager_repository import ReportingManagerRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.reporting_manager import (
    ReportingManagerAssign,
    ReportingManagerListResponse,
    ReportingManagerResponse,
)
from app.rbac.services.audit_log_service import AuditLogService
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
        audit_log_service=AuditLogService(
            audit_log_repository=AuditLogRepository(db),
        ),
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

    Authorization is enforced inside the service
    (`ReportingManagerService.ensure_can_manage_mapping`): Super
    Admin/Site Lead (via `org:manage_reporting_managers`) may assign
    any Account Manager; an Account Manager with no such permission
    may only assign themselves.
    """

    return await service.assign(data, actor=current_user)


@router.get(
    "",
    response_model=ReportingManagerListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Reporting Manager Assignments",
)
async def list_reporting_managers(
    account_manager_id: UUID | None = None,
    category_id: UUID | None = None,
    service: ReportingManagerService = Depends(get_reporting_manager_service),
    current_user=Depends(get_current_active_user),
):
    """
    Every Reporting Manager <-> category assignment, optionally
    filtered to one Account Manager or one category. If both filters
    are supplied, category_id takes precedence.

    A holder of `org:manage_reporting_managers` sees the full,
    optionally-filtered list, unchanged. An Account Manager without
    that permission is scoped to their own mappings only (further
    filtered to `category_id` when supplied) — see
    `ReportingManagerService.list_visible`.
    """

    items = await service.list_visible(
        current_user, account_manager_id=account_manager_id, category_id=category_id
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

    Authorization is enforced inside the service after the mapping is
    looked up (`ReportingManagerService.ensure_can_manage_mapping`):
    Super Admin/Site Lead may revoke any mapping; an Account Manager
    without that permission may only revoke their own.
    """

    await service.revoke(mapping_id, actor=current_user)

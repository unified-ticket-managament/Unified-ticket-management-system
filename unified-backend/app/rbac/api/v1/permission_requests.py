from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.rbac.repositories import (
    AuditLogRepository,
    PermissionOverrideRepository,
    PermissionRepository,
    PermissionRequestRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
)
from app.rbac.schemas.permission import PermissionResponse
from app.rbac.schemas.permission_request import (
    EligibleApproverRolesResponse,
    PermissionRequestApprove,
    PermissionRequestCreate,
    PermissionRequestReject,
    PermissionRequestResponse,
)
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.organization_service import OrganizationService
from app.rbac.services.permission_override_service import PermissionOverrideService
from app.rbac.services.permission_request_service import PermissionRequestService
from app.rbac.services.permission_resolver import PermissionResolverService
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService

router = APIRouter(
    prefix="/permission-requests",
    tags=["Permission Requests"],
)


# --------------------------------------------------
# Dependency
# --------------------------------------------------


def get_permission_request_service(
    db: AsyncSession = Depends(get_db),
) -> PermissionRequestService:
    """
    Returns PermissionRequestService instance. Builds its own
    PermissionOverrideService internally (same wiring as
    api/v1/permission_overrides.py's own factory) so approval can
    delegate the actual grant to it — this router never constructs a
    UserPermissionOverride itself.
    """

    role_permission_repository = RolePermissionRepository(db)
    permission_override_repository = PermissionOverrideRepository(db)
    permission_request_repository = PermissionRequestRepository(db)

    permission_resolver = PermissionResolverService(
        role_permission_repository=role_permission_repository,
        permission_override_repository=permission_override_repository,
    )

    organization_service = OrganizationService(
        user_repository=UserRepository(db),
        role_repository=RoleRepository(db),
    )

    audit_log_service = AuditLogService(
        audit_log_repository=AuditLogRepository(db),
    )

    permission_override_service = PermissionOverrideService(
        user_repository=UserRepository(db),
        permission_repository=PermissionRepository(db),
        permission_override_repository=permission_override_repository,
        organization_service=organization_service,
        permission_resolver=permission_resolver,
        audit_log_service=audit_log_service,
    )

    return PermissionRequestService(
        user_repository=UserRepository(db),
        role_repository=RoleRepository(db),
        permission_repository=PermissionRepository(db),
        role_permission_repository=role_permission_repository,
        permission_request_repository=permission_request_repository,
        permission_override_service=permission_override_service,
        permission_resolver=permission_resolver,
        audit_log_service=audit_log_service,
        notification_service=NotificationService(NotificationRepository(db)),
    )


# --------------------------------------------------
# Eligible Permissions
# --------------------------------------------------


@router.get(
    "/eligible-permissions",
    response_model=list[PermissionResponse],
    status_code=status.HTTP_200_OK,
    summary="List permissions the current user doesn't already have",
)
async def list_eligible_permissions(
    service: PermissionRequestService = Depends(get_permission_request_service),
    current_user=Depends(get_current_active_user),
):
    return await service.list_eligible_permissions(current_user)


# --------------------------------------------------
# Eligible Approver Roles
# --------------------------------------------------


@router.get(
    "/eligible-approver-roles",
    response_model=EligibleApproverRolesResponse,
    status_code=status.HTTP_200_OK,
    summary="List roles authorized to grant a given permission",
)
async def list_eligible_approver_roles(
    permission_id: UUID = Query(...),
    service: PermissionRequestService = Depends(get_permission_request_service),
    current_user=Depends(get_current_active_user),
):
    roles = await service.list_eligible_approver_roles(permission_id)
    return EligibleApproverRolesResponse(roles=roles)


# --------------------------------------------------
# Create Request
# --------------------------------------------------


@router.post(
    "",
    response_model=PermissionRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a permission you don't currently have",
)
async def create_permission_request(
    request: PermissionRequestCreate,
    service: PermissionRequestService = Depends(get_permission_request_service),
    current_user=Depends(get_current_active_user),
):
    return await service.create_request(current_user, request)


# --------------------------------------------------
# My Requests
# --------------------------------------------------


@router.get(
    "/mine",
    response_model=list[PermissionRequestResponse],
    status_code=status.HTTP_200_OK,
    summary="List the current user's own permission requests",
)
async def list_my_permission_requests(
    service: PermissionRequestService = Depends(get_permission_request_service),
    current_user=Depends(get_current_active_user),
):
    return await service.list_mine(current_user)


# --------------------------------------------------
# Pending For Review
# --------------------------------------------------


@router.get(
    "/pending-for-review",
    response_model=list[PermissionRequestResponse],
    status_code=status.HTTP_200_OK,
    summary="List pending permission requests the current user can review",
)
async def list_pending_for_review(
    service: PermissionRequestService = Depends(get_permission_request_service),
    current_user=Depends(get_current_active_user),
):
    return await service.list_pending_for_review(current_user)


# --------------------------------------------------
# Approve
# --------------------------------------------------


@router.post(
    "/{request_id}/approve",
    response_model=PermissionRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve a pending permission request",
)
async def approve_permission_request(
    request_id: UUID,
    request: PermissionRequestApprove,
    service: PermissionRequestService = Depends(get_permission_request_service),
    current_user=Depends(get_current_active_user),
):
    return await service.approve(current_user, request_id, request)


# --------------------------------------------------
# Reject
# --------------------------------------------------


@router.post(
    "/{request_id}/reject",
    response_model=PermissionRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject a pending permission request",
)
async def reject_permission_request(
    request_id: UUID,
    request: PermissionRequestReject,
    service: PermissionRequestService = Depends(get_permission_request_service),
    current_user=Depends(get_current_active_user),
):
    return await service.reject(current_user, request_id, request)

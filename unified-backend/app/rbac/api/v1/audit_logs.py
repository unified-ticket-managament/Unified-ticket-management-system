from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.rbac.repositories.audit_log_repository import AuditLogRepository
from app.rbac.schemas.audit_log import (
    AuditLogCreate,
    AuditLogListResponse,
    AuditLogResponse,
)
from app.rbac.services.access_control import ensure_has_permission
from app.rbac.services.audit_log_service import AuditLogService

router = APIRouter(
    prefix="/audit-logs",
    tags=["Audit Logs"],
)

# This table is system-level administration (logins, password changes,
# user/role CRUD, permission overrides/requests) — org-wide with no
# client/ticket/team concept to scope by, unlike app.ticketing's own
# per-ticket audit trail (see TicketService.list_all_audit_logs, which
# every other role reaches instead via GET /tickets/audit-logs). Every
# role's own audit-log requirements are already satisfied by that other
# endpoint except Super Admin's — see the Audit Logs role-scoping notes
# in CLAUDE.md.
SUPER_ADMIN_ROLE_NAME = "Super Admin"


# --------------------------------------------------
# Dependency
# --------------------------------------------------


def get_audit_log_service(
    db: AsyncSession = Depends(get_db),
) -> AuditLogService:
    """
    Returns AuditLogService instance.
    """

    repository = AuditLogRepository(db)

    return AuditLogService(
        audit_log_repository=repository,
    )


# --------------------------------------------------
# Create Audit Log
# --------------------------------------------------


@router.post(
    "",
    response_model=AuditLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Audit Log",
)
async def create_audit_log(
    log_data: AuditLogCreate,
    service: AuditLogService = Depends(get_audit_log_service),
    current_user=Depends(get_current_active_user),
):
    """
    Create a new audit log.

    Super Admin only — this route is not the system's real audit-writing
    path (every real action logs itself via AuditLogService.create_log
    called directly, server-side, from the service that performed the
    action); it exists only as a manual/administrative escape hatch.
    Previously had no authorization check at all beyond authentication,
    meaning any logged-in user of any role could forge an arbitrary
    audit log entry. No legitimate caller (frontend or backend) invokes
    this route today — confirmed by repo-wide search — so this is a
    pure hardening change with no behavioral impact on any real flow.
    """

    if current_user.role.name != SUPER_ADMIN_ROLE_NAME:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Super Admin can create system-level audit logs.",
        )

    return await service.create_log(log_data)


# --------------------------------------------------
# List Audit Logs
# --------------------------------------------------


@router.get(
    "",
    response_model=AuditLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Audit Logs",
)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service: AuditLogService = Depends(get_audit_log_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns paginated audit logs. Super Admin only — see this
    module's own top-of-file note on why every other role's audit-log
    needs are served by GET /tickets/audit-logs instead.
    """

    if current_user.role.name != SUPER_ADMIN_ROLE_NAME:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Super Admin can view system-level audit logs.",
        )

    logs, total = await service.list_logs(
        page=page,
        page_size=page_size,
    )

    return AuditLogListResponse(
        logs=logs,
        total=total,
    )


# --------------------------------------------------
# Get Audit Log
# --------------------------------------------------


@router.get(
    "/{audit_log_id}",
    response_model=AuditLogResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Audit Log",
)
async def get_audit_log(
    audit_log_id: UUID,
    service: AuditLogService = Depends(get_audit_log_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns audit log details.
    """

    ensure_has_permission(current_user, "audit:view")

    return await service.get_log(
        audit_log_id,
    )


# --------------------------------------------------
# Get User Audit Logs
# --------------------------------------------------


@router.get(
    "/user/{user_id}",
    response_model=list[AuditLogResponse],
    status_code=status.HTTP_200_OK,
    summary="Get User Audit Logs",
)
async def get_user_audit_logs(
    user_id: UUID,
    service: AuditLogService = Depends(get_audit_log_service),
    current_user=Depends(get_current_active_user),
):
    """
    Returns all audit logs for a user.
    """

    ensure_has_permission(current_user, "audit:view")

    return await service.get_user_logs(
        user_id,
    )


# --------------------------------------------------
# Delete Audit Log
# --------------------------------------------------


@router.delete(
    "/{audit_log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Audit Log",
)
async def delete_audit_log(
    audit_log_id: UUID,
    service: AuditLogService = Depends(get_audit_log_service),
    current_user=Depends(get_current_active_user),
):
    """
    Delete an audit log.

    Super Admin only — same reasoning as create_audit_log above.
    Audit logs are meant to be an append-only, permanent record;
    previously this route had no authorization check at all beyond
    authentication, meaning any logged-in user of any role could
    permanently delete any audit log row. Confirmed no legitimate
    caller (frontend or backend) invokes this route today, so this is
    a pure hardening change.
    """

    if current_user.role.name != SUPER_ADMIN_ROLE_NAME:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Super Admin can delete system-level audit logs.",
        )

    await service.delete_log(
        audit_log_id,
    )
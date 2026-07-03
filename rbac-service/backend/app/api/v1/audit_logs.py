from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_active_user
from app.database.session import get_db
from app.repositories.audit_log_repository import AuditLogRepository
from app.schemas.audit_log import (
    AuditLogCreate,
    AuditLogListResponse,
    AuditLogResponse,
)
from app.services.audit_log_service import AuditLogService

router = APIRouter(
    prefix="/audit-logs",
    tags=["Audit Logs"],
)


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
    """

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
    Returns paginated audit logs.
    """

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
    """

    await service.delete_log(
        audit_log_id,
    )
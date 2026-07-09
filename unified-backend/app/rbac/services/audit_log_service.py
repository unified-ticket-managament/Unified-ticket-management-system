from uuid import UUID

from fastapi import HTTPException, status

from app.rbac.models.audit_log import AuditLog
from app.rbac.repositories import AuditLogRepository
from app.rbac.schemas.audit_log import AuditLogCreate


class AuditLogService:
    """
    Business logic for Audit Logs.
    """

    def __init__(
        self,
        audit_log_repository: AuditLogRepository,
    ):
        self.audit_log_repository = audit_log_repository

    # --------------------------------------------------
    # Create Log
    # --------------------------------------------------

    async def create_log(
        self,
        log_data: AuditLogCreate,
    ) -> AuditLog:

        log = AuditLog(
            user_id=log_data.user_id,
            action=log_data.action,
            entity_type=log_data.entity_type,
            entity_id=log_data.entity_id,
            old_value=log_data.old_value,
            new_value=log_data.new_value,
            ip_address=log_data.ip_address,
            user_agent=log_data.user_agent,
        )

        return await self.audit_log_repository.create(log)

    # --------------------------------------------------
    # Get Log
    # --------------------------------------------------

    async def get_log(
        self,
        audit_log_id: UUID,
    ) -> AuditLog:

        log = await self.audit_log_repository.get_by_id(
            audit_log_id
        )

        if log is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Audit log not found.",
            )

        return log

    # --------------------------------------------------
    # Get All Logs
    # --------------------------------------------------

    async def list_logs(
        self,
        page: int = 1,
        page_size: int = 20,
    ):

        return await self.audit_log_repository.get_all(
            page,
            page_size,
        )

    # --------------------------------------------------
    # Get User Logs
    # --------------------------------------------------

    async def get_user_logs(
        self,
        user_id: UUID,
    ):

        return await self.audit_log_repository.get_user_logs(
            user_id
        )

    # --------------------------------------------------
    # Delete Log
    # --------------------------------------------------

    async def delete_log(
        self,
        audit_log_id: UUID,
    ):

        log = await self.get_log(audit_log_id)

        await self.audit_log_repository.delete(log)
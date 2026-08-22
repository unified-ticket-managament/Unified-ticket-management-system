from uuid import UUID

from sqlalchemy import func, select

from app.core.impersonation_context import get_impersonator
from app.rbac.models.audit_log import AuditLog

from .base import BaseRepository


class AuditLogRepository(BaseRepository):
    """
    Repository for Audit Log operations.
    """

    async def create(
        self,
        audit_log: AuditLog,
    ) -> AuditLog:
        # See app/ticketing/repositories/audit_log_repository.py's
        # identical addition for the full rationale — both audit
        # systems need this, since either can write a row during an
        # impersonated session (e.g. this table's own
        # user_impersonation.started/ended rows aside, a Super Admin
        # impersonating a role that holds user:update/permission:update
        # etc. can still trigger a user.*/role.*/permission.* row here).
        impersonator = get_impersonator()
        if impersonator is not None:
            audit_log.impersonator_id = impersonator[0]
            audit_log.impersonator_name = impersonator[1]

        self.db.add(audit_log)

        await self.db.flush()
        await self.db.refresh(audit_log)

        return audit_log

    async def get_by_id(
        self,
        audit_log_id: UUID,
    ) -> AuditLog | None:

        result = await self.db.execute(
            select(AuditLog).where(
                AuditLog.audit_log_id == audit_log_id
            )
        )

        return result.scalar_one_or_none()

    async def get_all(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AuditLog], int]:

        total = (
            await self.db.execute(
                select(func.count()).select_from(AuditLog)
            )
        ).scalar_one()

        result = await self.db.execute(
            select(AuditLog)
            .order_by(AuditLog.timestamp.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        logs = result.scalars().all()

        return list(logs), total

    async def get_user_logs(
        self,
        user_id: UUID,
    ) -> list[AuditLog]:

        result = await self.db.execute(
            select(AuditLog)
            .where(AuditLog.user_id == user_id)
            .order_by(AuditLog.timestamp.desc())
        )

        return list(result.scalars().all())

    async def delete(
        self,
        audit_log: AuditLog,
    ) -> None:

        await self.db.delete(audit_log)
        await self.db.flush()
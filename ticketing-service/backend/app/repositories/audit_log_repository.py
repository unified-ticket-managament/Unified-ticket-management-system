# audit_log_repository.py

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import ActorRole, AuditEntityType, AuditEventType
from app.models.audit_log import AuditLog

#audit_log_repository.py
class AuditLogRepository:
    """
    Write-mostly access to the ticket_audit_logs table (named that,
    not audit_logs, to avoid colliding with an unrelated table of
    that name already owned by another service in this shared DB).

    Audit rows are immutable once written — there is intentionally
    no update() or delete() here, only create() and reads.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        entity_type: AuditEntityType,
        entity_id: UUID,
        event_type: AuditEventType,
        actor_id: UUID | None,
        actor_name: str,
        actor_role: ActorRole,
        old_values: dict[str, Any] | None,
        new_values: dict[str, Any] | None,
    ) -> AuditLog:
        audit_log = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_id=actor_id,
            actor_name=actor_name,
            actor_role=actor_role,
            old_values=old_values,
            new_values=new_values,
        )

        self.db.add(audit_log)

        # Flush only — never commit. The request's get_db()
        # dependency commits once at the end of the request, so
        # this row lands in the exact same transaction as whatever
        # ticket/interaction/attachment change triggered it: both
        # succeed together or both roll back together.
        await self.db.flush()
        await self.db.refresh(audit_log)

        return audit_log

    async def list_by_ticket(
        self,
        ticket_id: UUID,
    ) -> list[AuditLog]:
        """
        Every audit row related to a ticket: the direct
        entity_type=TICKET rows, plus the INTERACTION / ATTACHMENT
        rows that carry this ticket_id in their new_values JSONB
        (note/reply/hide/upload events are logged against the
        interaction/attachment id, but deliberately stamp the owning
        ticket_id into new_values so a per-ticket view is possible
        without a schema change). Newest first.
        """

        result = await self.db.execute(
            select(AuditLog)
            .where(
                or_(
                    (AuditLog.entity_type == AuditEntityType.TICKET)
                    & (AuditLog.entity_id == ticket_id),
                    # JSONB ->> is text — compare against the string
                    # form of the UUID.
                    AuditLog.new_values["ticket_id"].astext == str(ticket_id),
                )
            )
            .order_by(AuditLog.created_at.desc())
        )
        return list(result.scalars().all())

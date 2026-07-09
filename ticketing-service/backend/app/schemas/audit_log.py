from datetime import datetime
from typing import Any
from uuid import UUID

from app.enums import ActorRole, AuditEntityType, AuditEventType
from app.schemas.common import ORMBase

#audit_log.py
class AuditLogResponse(ORMBase):
    """
    Read-only view of a single audit_logs row. There is no
    corresponding create/update request schema — rows are written
    exclusively through AuditLogService.log_event(), never via a
    user-facing request body.
    """

    audit_id: UUID
    entity_type: AuditEntityType
    entity_id: UUID
    event_type: AuditEventType
    actor_id: UUID | None
    actor_name: str
    actor_role: ActorRole
    old_values: dict[str, Any] | None
    new_values: dict[str, Any] | None
    created_at: datetime


class TicketAuditLogResponse(AuditLogResponse):
    """
    Same shape as AuditLogResponse, with the owning ticket's id/title
    attached — used by the batched GET /tickets/audit-logs endpoint so
    the Audit Log page doesn't have to zip ticket titles onto rows
    itself after fetching each ticket's trail one at a time.
    """

    ticket_id: UUID
    ticket_title: str

from .ticket_enums import TicketPriority, TicketStatus
#enums/__init__.py
from .interaction_enums import (
    InteractionDirection,
    InteractionStatus,
)
from .audit_enums import (
    ActorRole,
    AuditEntityType,
    AuditEventType,
)
from .edit_access_enums import EditAccessStatus
from .sla_enums import SLAClockStatus
from .escalation_enums import (
    CLOSED_REASON_MANUALLY_CLOSED,
    CLOSED_REASON_TICKET_RESOLVED,
    TRIGGERED_BY_AUTO_SLA_BREACH,
    TRIGGERED_BY_MANUAL,
    EscalationLevel,
    EscalationStatus,
)

__all__ = [
    "TicketStatus",
    "TicketPriority",
    "InteractionStatus",
    "InteractionDirection",
    "ActorRole",
    "AuditEntityType",
    "AuditEventType",
    "EditAccessStatus",
    "SLAClockStatus",
    "EscalationLevel",
    "EscalationStatus",
    "TRIGGERED_BY_MANUAL",
    "TRIGGERED_BY_AUTO_SLA_BREACH",
    "CLOSED_REASON_TICKET_RESOLVED",
    "CLOSED_REASON_MANUALLY_CLOSED",
]
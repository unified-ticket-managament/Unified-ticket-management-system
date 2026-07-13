from shared_models.database import Base

from .client import Client
from .ticket import Ticket
from .interaction import Interaction
from .attachment import Attachment
from .audit_log import AuditLog
from .mail_folder import MailFolder
from .ticket_relation import TicketRelation
from .ticket_edit_access_request import TicketEditAccessRequest
from .sla_policy import SLAPolicy
from .first_response_sla import FirstResponseSLA
from .resolution_sla import ResolutionSLA
from .resolution_sla_pause_interval import ResolutionSLAPauseInterval
from .sla_breach_notification import SLABreachNotification
from .message_read_receipt import MessageReadReceipt
from .ticket_escalation import TicketEscalation

__all__ = [
    "Base",
    "Client",
    "Ticket",
    "Interaction",
    "Attachment",
    "AuditLog",
    "MailFolder",
    "TicketRelation",
    "TicketEditAccessRequest",
    "SLAPolicy",
    "FirstResponseSLA",
    "ResolutionSLA",
    "ResolutionSLAPauseInterval",
    "SLABreachNotification",
    "MessageReadReceipt",
    "TicketEscalation",
]
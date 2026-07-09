from shared_models.database import Base

from .client import Client
from .ticket import Ticket
from .interaction import Interaction
from .attachment import Attachment
from .audit_log import AuditLog
from .mail_folder import MailFolder
from .ticket_relation import TicketRelation
from .ticket_edit_access_request import TicketEditAccessRequest

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
]
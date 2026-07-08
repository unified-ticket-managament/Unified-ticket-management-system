from shared_models.database import Base

from .client import Client
from .ticket import Ticket
from .interaction import Interaction
from .attachment import Attachment
from .audit_log import AuditLog
from .mail_folder import MailFolder
from .ticket_relation import TicketRelation

__all__ = [
    "Base",
    "Client",
    "Ticket",
    "Interaction",
    "Attachment",
    "AuditLog",
    "MailFolder",
    "TicketRelation",
]
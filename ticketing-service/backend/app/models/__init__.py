from shared_models.database import Base

from .ticket import Ticket
from .interaction import Interaction
from .attachment import Attachment
from .audit_log import AuditLog

__all__ = [
    "Base",
    "Ticket",
    "Interaction",
    "Attachment",
    "AuditLog",
]
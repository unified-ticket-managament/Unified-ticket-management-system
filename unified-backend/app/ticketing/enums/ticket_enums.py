from enum import Enum

#ticket_enums.py
class TicketStatus(str, Enum):
    """
    Current status of a ticket.
    """

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING = "PENDING"
    WAITING_FOR_CLIENT = "WAITING_FOR_CLIENT"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class TicketPriority(str, Enum):
    """
    Ticket priority.

    CRITICAL is deliberately not a manually-selectable tier — it is set
    automatically, once, when a ticket's internal escalation workflow
    creates its first escalation (see EscalationService), and stays
    permanently thereafter (no reversion on acknowledge/close). Every
    manual "Change Priority" surface must keep excluding it; only
    display/filter surfaces should include it.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
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
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
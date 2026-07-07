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


class TicketCategory(str, Enum):
    """
    Fixed category list for new tickets, replacing free-text
    ticket_type input (which had accumulated inconsistent casing —
    "BILLING"/"Billing"/"billing" as distinct values). Validated at
    the Pydantic layer only — `Ticket.ticket_type` stays a plain
    String(50) column, not a Postgres enum, so this list can change
    without a migration. Existing free-text rows are untouched and
    still display fine (TicketResponse.ticket_type stays str).
    """

    TECHNICAL = "TECHNICAL"
    BILLING = "BILLING"
    HIRING = "HIRING"
    GENERAL = "GENERAL"
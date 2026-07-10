from enum import Enum


class EditAccessStatus(str, Enum):
    """
    Lifecycle of a per-ticket edit-access request — a Staff member (or
    anyone else lacking the ticket:editother_ticket permission) asking to
    work a ticket they're not the assigned agent on, reviewed by
    whoever already holds ticket:editother_ticket for it.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

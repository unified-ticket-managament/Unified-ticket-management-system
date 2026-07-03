# access_control.py


from fastapi import HTTPException, status
from shared_models.models import User

from app.enums import TicketStatus
from app.models.ticket import Ticket

# Every RBAC role except Viewer (the client-facing role) can log into
# Ticketing and act as an agent.
AGENT_ROLE_NAMES = {"Staff", "Team Lead", "Manager", "Super Admin"}

# Team Lead/Manager/Super Admin can see every ticket regardless of
# assignment; Staff stays restricted to tickets assigned to them (or
# unassigned ones).
SUPERVISOR_ROLE_NAMES = {"Team Lead", "Manager", "Super Admin"}


def ensure_ticket_not_closed(ticket: Ticket) -> None:
    """
    A closed ticket is terminal for every action except reopening it
    (changing its status back off CLOSED) — replies, internal notes,
    priority changes, agent transfers, and attachment uploads are all
    blocked. Status change itself is deliberately exempt, since it's
    the only way to reopen a closed ticket.
    """

    if ticket.current_status == TicketStatus.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This ticket is closed. Reopen it before performing further actions.",
        )


def ensure_agent_can_view_ticket(
    ticket: Ticket,
    current_user: User,
) -> None:
    """
    A ticket, and everything scoped to it (its interaction timeline
    included), is visible only to the agent it's assigned to. An
    unassigned ticket stays visible to everyone. Team Lead/Manager/
    Super Admin bypass this check entirely and can see every ticket,
    regardless of assignment.
    """

    if current_user.role.name in SUPERVISOR_ROLE_NAMES:
        return

    if ticket.agent_id is None:
        return

    if ticket.agent_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this ticket.",
        )

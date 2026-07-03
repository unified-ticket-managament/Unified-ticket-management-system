# access_control.py


from fastapi import HTTPException, status

from app.enums import TicketStatus
from app.models.ticket import Ticket
from app.repositories.user_repository import UserRepository


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


async def ensure_agent_can_view_ticket(
    ticket: Ticket,
    agent_name: str | None,
    user_repository: UserRepository,
) -> None:
    """
    A ticket, and everything scoped to it (its interaction
    timeline included), is visible only to the agent it's
    assigned to. An unassigned ticket stays visible to everyone.
    `agent_name` is the frontend's "acting as" selection; omit
    it to skip the check entirely.
    """

    if agent_name is None or ticket.agent_id is None:
        return

    agent = await user_repository.get_active_staff_by_name(agent_name)

    if agent is None or ticket.agent_id != agent.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this ticket.",
        )

# access_control.py


from fastapi import HTTPException, status
from shared_models.models import User

from app.enums import TicketStatus
from app.models.ticket import Ticket

# Every RBAC role except Viewer (the client-facing role) can log into
<<<<<<< Updated upstream
# Ticketing and act as an agent.
AGENT_ROLE_NAMES = {"Staff", "Team Lead", "Account Manager", "Site Lead", "Super Admin"}

# Team Lead/Account Manager/Site Lead/Super Admin can see every ticket
# regardless of assignment; Staff stays restricted to tickets assigned
# to them (or unassigned ones).
SUPERVISOR_ROLE_NAMES = {"Team Lead", "Account Manager", "Site Lead", "Super Admin"}
=======
# Ticketing and act as an agent. RBAC's roles are Super Admin, Team
# Lead, Staff, Viewer, Account Manager, Site Lead — there is no role
# literally named "Manager".
AGENT_ROLE_NAMES = {"Staff", "Team Lead", "Account Manager", "Site Lead", "Super Admin"}

# Org hierarchy (per CEO's model):
#   - Super Admin / Site Lead: full oversight — every client's
#     tickets and inbox, unrestricted.
#   - Account Manager: scoped to only their own clients' tickets and
#     inbox (see ACCOUNT_MANAGER_ROLE_NAME below).
#   - Team Lead: works tickets in their category regardless of which
#     AM owns the client, plus monitors their direct-report Staff.
#   - Staff: works category tickets from the shared pool, regardless
#     of AM.
# Category-based routing for Team Lead/Staff is not implemented yet
# (deferred — no category-ownership model defined), so both currently
# stay unrestricted, same as before. Only Super Admin/Site Lead get
# the full-oversight escape hatch (e.g. the AM inbox's "All Inboxes"
# tab) — Team Lead's oversight is over their own staff, not every
# other AM's mail.
SUPERVISOR_ROLE_NAMES = {"Super Admin", "Site Lead"}

# The role that owns Client.account_manager_id — i.e. the "Account
# Manager" from the CEO's org model.
ACCOUNT_MANAGER_ROLE_NAME = "Account Manager"
>>>>>>> Stashed changes


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
<<<<<<< Updated upstream
    A ticket, and everything scoped to it (its interaction timeline
    included), is visible only to the agent it's assigned to. An
    unassigned ticket stays visible to everyone. Team Lead/Account
    Manager/Site Lead/Super Admin bypass this check entirely and can
    see every ticket, regardless of assignment.
=======
    Deliberately a no-op now. Under the shared-pool + claim workflow,
    every agent role must be able to browse every ticket (claimed or
    not) to decide what to pick up, so per-assignment view gating no
    longer applies. Kept as a named call site — not deleted — so a
    future task (teams/skill-based routing) has one place to
    reintroduce narrower visibility instead of scattering checks
    across every route again.
>>>>>>> Stashed changes
    """

    return

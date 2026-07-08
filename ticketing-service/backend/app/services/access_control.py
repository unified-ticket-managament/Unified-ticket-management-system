# access_control.py


from fastapi import HTTPException, status
from shared_models.models import User

from app.enums import TicketStatus
from app.models.ticket import Ticket

# Every RBAC role except Viewer (the client-facing role) can log into
# Ticketing and act as an agent.
AGENT_ROLE_NAMES = {"Staff", "Team Lead", "Account Manager", "Site Lead", "Super Admin"}

# Team Lead/Account Manager/Site Lead/Super Admin can see every ticket
# regardless of assignment; Staff stays restricted to tickets assigned
# to them (or unassigned ones).
SUPERVISOR_ROLE_NAMES = {"Team Lead", "Account Manager", "Site Lead", "Super Admin"}

# The role that owns Client.account_manager_id — i.e. the "Account
# Manager" from the CEO's org model. Used by client_service.py (who
# may be assigned as an AM) and ticket_service.py (their own-clients
# ticket scoping).
ACCOUNT_MANAGER_ROLE_NAME = "Account Manager"

# Roles whose ticket visibility is scoped to their own work-
# specialization category (Eligibility, AR, Claims, ... — see
# shared_models.models.Category). Each category is its own shared
# pool: a Team Lead/Staff only sees/claims tickets filed under the
# category they were created with (RBAC enforces this as required
# for these two roles — see CATEGORY_REQUIRED_ROLE_NAMES in
# rbac-service's user_service.py). Account Manager/Site Lead/Super
# Admin are deliberately excluded — Account Manager is scoped by
# client ownership instead (see ticket_service._resolve_owned_client_ids),
# and Site Lead/Super Admin retain full oversight by design.
CATEGORY_SCOPED_ROLE_NAMES = {"Team Lead", "Staff"}

# Roles with an unrestricted, org-wide Mail inbox — every client,
# every team, every agent's threads (InboxService.get_inbox). Site
# Lead is the CEO's "global inbox" role; Super Admin retains the same
# oversight it has everywhere else. Deliberately NOT the same set as
# SUPERVISOR_ROLE_NAMES above: Team Lead and Account Manager can
# still bypass ownership scoping for ticket-level actions like
# reassignment, but neither gets the raw "see every client's mail"
# escape hatch that used to live behind view=all/scope=all for every
# SUPERVISOR_ROLE_NAMES member — Team Lead is now category-scoped and
# Account Manager stays client-scoped for Mail specifically.
GLOBAL_INBOX_ROLE_NAMES = {"Site Lead", "Super Admin"}

# The only role allowed to use the internal "Create Dummy Mail"
# simulator (POST /emails/dummy) — a testing/demo tool, not the real
# inbound-email transport route (POST /emails/incoming, which stays
# unauthenticated for the future Graph/n8n webhook and is untouched
# by this restriction).
DUMMY_MAIL_ROLE_NAMES = {"Site Lead"}


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
    Category-scoped visibility for Team Lead/Staff (see
    CATEGORY_SCOPED_ROLE_NAMES): each work-specialization category
    has its own shared pool, and a Team Lead/Staff may only view (or
    act on, via the other services that call this same gate) tickets
    filed under their own category — not just any unassigned ticket.
    Account Manager, Site Lead, and Super Admin are unrestricted here
    (Account Manager is separately scoped by client ownership in
    ticket_service.py; Site Lead/Super Admin keep full oversight).

    A Team Lead/Staff with no category assigned sees nothing rather
    than everything — category is required at user-creation time for
    these two roles, so this should only ever bite a pre-existing
    user created before that constraint existed, and "sees nothing"
    is the safe failure mode, matching the Account Manager's
    owns-no-clients-sees-nothing convention below.
    """

    if current_user.role.name not in CATEGORY_SCOPED_ROLE_NAMES:
        return

    user_category_name = (
        current_user.category.category_name.value
        if current_user.category is not None
        else None
    )

    if user_category_name is None or ticket.ticket_type != user_category_name:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this ticket.",
        )


async def ensure_agent_can_view_pending_interaction(
    interaction,
    current_user: User,
    client_repository,
) -> None:
    """
    Gates a still-pending (pre-ticket) Mail item the same way
    InboxService.get_inbox already scopes the list view: the Account
    Manager who owns the item's client, or a global-inbox role (Site
    Lead/Super Admin). Team Lead/Staff are deliberately excluded —
    they never see a pending item in their own inbox list either, so
    a crafted request for its interaction_id shouldn't work either.

    Shared by InteractionService (claim/archive/snooze/tags/folder/
    drafts) and OpenEmailService (opening the thread itself) so
    "can act on it" and "can see it" stay the same rule.
    """

    if current_user.role.name in GLOBAL_INBOX_ROLE_NAMES:
        return

    client = (
        await client_repository.get_by_id(interaction.client_id)
        if client_repository is not None and interaction.client_id is not None
        else None
    )

    if client is None or client.account_manager_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this item.",
        )


def ensure_can_reassign_ticket(current_user: User) -> None:
    """
    Only Team Lead/Account Manager/Site Lead/Super Admin may move a
    ticket to a specific *other* named agent (InteractionService.
    transfer_agent) — matches the already-designed permission matrix
    (`ticket:transfer` is Full for these roles, Override-only for
    Staff), which nothing enforced server-side until now.

    Deliberately NOT applied to claim_ticket: picking up an unclaimed
    ticket from the shared pool for *yourself* is Staff's normal
    daily workflow (see EmailService's own docstring: "staff pick up
    resulting tickets from the shared pool instead of being auto-
    assigned at intake") and must stay open to every agent role.
    """

    if current_user.role.name not in SUPERVISOR_ROLE_NAMES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a Team Lead, Account Manager, Site Lead, or Super Admin can reassign a ticket to another agent.",
        )

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


async def ensure_agent_can_act_on_ticket(
    ticket: Ticket,
    current_user: User,
    edit_access_repository=None,    
) -> None:
    """
    Working a ticket — replying, adding an internal note, changing
    status, uploading an attachment — is restricted to the agent it's
    actually assigned to. Teammates who share the same category can
    already see the ticket (ensure_agent_can_view_ticket, called first
    here) but not act on someone else's claimed work; an unclaimed
    ticket (agent_id is None) blocks everyone but supervisors until
    someone claims it. Supervisors (SUPERVISOR_ROLE_NAMES) bypass
    this, same as they bypass ownership scoping everywhere else in
    this file.

    Two further ways to act on a ticket you're not assigned to, both
    letting more than one person work the same ticket at once (see
    ticket:edit_ticket in seed.py's DEFAULT_ROLES): holding
    ticket:edit_ticket outright (by role default or a personal
    override — see rbac-service's permission_overrides), or having an
    approved, not-yet-expired per-ticket edit-access grant (see
    TicketEditAccessRequestRepository.has_active_grant) requested and
    reviewed via the edit-access endpoints. `edit_access_repository`
    is optional so callers that don't pass one simply skip the
    per-ticket-grant check (still get the permission-based bypass,
    which needs no repository).

    Deliberately NOT applied to claim_ticket (picking up an unclaimed
    ticket is how you become its assigned agent in the first place)
    or transfer_agent (already gated by ensure_can_reassign_ticket,
    which is supervisor-only regardless of current assignment).
    """

    ensure_agent_can_view_ticket(ticket, current_user)

    if current_user.role.name in SUPERVISOR_ROLE_NAMES:
        return

    if ticket.agent_id == current_user.user_id:
        return

    if has_permission(current_user, "ticket:edit_ticket"):
        return

    if edit_access_repository is not None and await edit_access_repository.has_active_grant(
        ticket.ticket_id, current_user.user_id
    ):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only the agent this ticket is assigned to can perform this action.",
    )


async def ensure_account_manager_owns_ticket_client(
    ticket: Ticket,
    current_user: User,
    client_repository,
) -> None:
    """
    `ensure_agent_can_view_ticket` only handles the Team Lead/Staff
    category gate — it deliberately no-ops for Account Manager, whose
    scoping is by client ownership instead. That ownership check lives
    in `ticket_service._resolve_owned_client_ids` for the ticket
    list/detail routes, but nothing in this module enforced it for
    interaction-level reads (the thread-fetch endpoint) until now — an
    Account Manager could open any ticket's conversation, not just
    their own clients'. Site Lead/Super Admin/Team Lead/Staff are
    untouched here (Team Lead/Staff already get their own gate from
    ensure_agent_can_view_ticket; Site Lead/Super Admin stay
    unrestricted everywhere by design).
    """

    if current_user.role.name != ACCOUNT_MANAGER_ROLE_NAME:
        return

    if ticket.client_company_id is None or client_repository is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this ticket.",
        )

    owned_client_ids = await client_repository.list_client_ids_by_account_manager(
        current_user.user_id
    )

    if ticket.client_company_id not in owned_client_ids:
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


def has_permission(current_user: User, permission_name: str) -> bool:
    """
    Non-raising check against the permission list threaded onto
    `current_user` from the decoded JWT's `permissions` claim (see
    dependencies/auth.py) — never a fresh network call back to RBAC,
    matching this service's verify-only design. A token issued before
    this claim existed, or one that's simply stale relative to a
    since-changed RBAC grant within its own TTL, degrades to an empty
    list rather than crashing.
    """

    permissions = getattr(current_user, "permissions", None) or []

    return permission_name in permissions


def ensure_has_permission(current_user: User, permission_name: str) -> None:
    """Raising wrapper around has_permission — 403s if it's missing."""

    if not has_permission(current_user, permission_name):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required permission: {permission_name}",
        )


def ensure_can_review_edit_access(
    ticket: Ticket,
    current_user: User,
) -> None:
    """
    Gates approving/rejecting a per-ticket edit-access request:
    reviewer must be able to see the ticket at all (the same category
    gate every other ticket action uses) and must hold
    ticket:edit_ticket themselves — the same permission that lets
    someone bypass ensure_agent_can_act_on_ticket's ownership check,
    so only someone who could already act on any ticket in scope can
    decide to let someone else in too.
    """

    ensure_agent_can_view_ticket(ticket, current_user)
    ensure_has_permission(current_user, "ticket:edit_ticket")


def ensure_can_reassign_ticket(current_user: User) -> None:
    """
    Only Team Lead/Account Manager/Site Lead/Super Admin may move a
    ticket to a specific *other* named agent (InteractionService.
    transfer_agent) — matches the already-designed permission matrix
    (`ticket:transfer` is Full for these roles, Override-only for
    Staff), which nothing enforced server-side until now.

    A Staff member with no override still falls through to
    ensure_has_permission, which 403s them (the pre-existing
    behavior); a Staff member individually granted `ticket:transfer`
    via a personal permission override (see permission_overrides in
    rbac-service) is let through by that same check instead.

    Deliberately NOT applied to claim_ticket: picking up an unclaimed
    ticket from the shared pool for *yourself* is Staff's normal
    daily workflow (see EmailService's own docstring: "staff pick up
    resulting tickets from the shared pool instead of being auto-
    assigned at intake") and must stay open to every agent role.
    """

    if current_user.role.name in SUPERVISOR_ROLE_NAMES:
        return

    ensure_has_permission(current_user, "ticket:transfer")

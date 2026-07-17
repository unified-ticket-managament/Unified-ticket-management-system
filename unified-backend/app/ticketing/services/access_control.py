# access_control.py


from fastapi import HTTPException, status
from shared_models.models import User

from app.ticketing.enums import EscalationStatus, TicketStatus
from app.ticketing.models.ticket import Ticket

# Every RBAC role except Viewer (the client-facing role) can log into
# Ticketing and act as an agent.
AGENT_ROLE_NAMES = {"Staff", "Team Lead", "Account Manager", "Site Lead", "Super Admin"}

# Team Lead/Account Manager/Site Lead/Super Admin can see every ticket
# regardless of assignment; Staff stays restricted to tickets assigned
# to them (or unassigned ones).
SUPERVISOR_ROLE_NAMES = {"Team Lead", "Account Manager", "Site Lead", "Super Admin"}

# Roles allowed to hand a ticket directly to a Team Lead via
# InteractionService.transfer_agent, outside any active escalation —
# the business Organization Structure's rule that every Account
# Manager can assign work to ANY Team Lead, regardless of department
# (see root CLAUDE.md's "Organization Structure" section — this is
# deliberately independent of, and not scoped by, the org-chart
# manager_id reporting line). Deliberately excludes Team Lead itself
# (a Team Lead's own scope is its own category's Staff, not other
# Team Leads — it is "the operational head of a business category",
# not a reporting manager) and Staff (already blocked from reaching
# transfer_agent at all by ensure_can_reassign_ticket).
TEAM_LEAD_TRANSFER_ROLE_NAMES = {"Account Manager", "Site Lead", "Super Admin"}

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

# Who can receive or manage an internal escalation, and therefore who
# the ticket-list page's "Escalated" tab is shown to at all — Account
# Manager/Team Lead (the two roles TicketEscalation's own ownership
# chain can name as an owner) plus Site Lead/Super Admin (company-wide
# overseers, same as GLOBAL_INBOX_ROLE_NAMES elsewhere). Staff is
# deliberately excluded: an escalated ticket assigned to Staff still
# shows up in their own My Tickets tab (see the escalated-first
# ordering there), just not this separate oversight view.
ESCALATION_TAB_ROLE_NAMES = {"Account Manager", "Team Lead", "Site Lead", "Super Admin"}

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
    escalation_repository=None,
    escalation_handling_sla_repository=None,
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

    A non-CLOSED escalated ticket is frozen for its currently-assigned
    agent until the escalation has actually been *accepted* — not
    merely acknowledged. Acknowledging alone (EscalationService.
    acknowledge) only stops the ack-window auto-advance; the Resolution
    SLA (and this freeze) only lift once a supervisor has *also*
    assigned the ticket to someone (claim/transfer/confirm-unchanged —
    see EscalationService._complete_acceptance), matching "Resolution
    SLA starts only after Acknowledge AND Assign." Whether acceptance
    has completed is read off the EscalationHandlingSLA table
    (`escalation_handling_sla_repository`, optional): a row exists for
    an escalation_id if and only if _complete_acceptance has already
    run for it (it's the one and only place that row gets created) —
    reusing that existing fact rather than adding a new column. If
    `escalation_handling_sla_repository` isn't supplied, this falls
    back to the older, coarser rule (frozen only while status is
    still ACTIVE i.e. never acknowledged at all) so existing callers
    that haven't been updated to pass it keep their prior behavior
    rather than becoming newly, incorrectly frozen forever. Checked
    right after the supervisor bypass above (deliberately not applied
    to supervisors themselves — acknowledging/assigning is how a
    supervisor is meant to interact with an active escalation, not
    this "work it normally" path). `escalation_repository` is
    optional, same convention as `edit_access_repository` below —
    callers that don't pass one simply skip this check entirely.

    Own-ticket access is gated by ticket:editown_ticket (default for
    every role, so this is normally a formality, but it's now a real,
    named, revocable-at-the-role-level permission rather than a bare
    hardcoded bypass). Acting on someone else's ticket needs one of:
    holding ticket:editother_ticket outright (by role default — Super
    Admin/Site Lead/Account Manager/Team Lead — or an unscoped
    personal override), or a ticket:editother_ticket override scoped
    to this one ticket_id specifically (see has_permission_for_ticket
    and rbac-service's scope_ticket_id on UserPermissionOverride —
    this is how a Staff member gets approved to work exactly one
    teammate's ticket, via the Permission Request workflow, without
    touching every other ticket in scope). A third, unrelated way to
    act on a ticket you're not assigned to is a ticketing-native,
    per-ticket edit-access grant (see
    TicketEditAccessRequestRepository.has_active_grant) requested and
    reviewed via the edit-access endpoints — a separate mechanism from
    the rbac-service permission-request one above, deliberately left
    untouched. `edit_access_repository` is optional so callers that
    don't pass one simply skip that check (still get the two
    permission-based bypasses, which need no repository).

    Deliberately NOT applied to claim_ticket (picking up an unclaimed
    ticket is how you become its assigned agent in the first place)
    or transfer_agent (already gated by ensure_can_reassign_ticket,
    which is supervisor-only regardless of current assignment).
    """

    ensure_agent_can_view_ticket(ticket, current_user)

    if current_user.role.name in SUPERVISOR_ROLE_NAMES:
        return

    if escalation_repository is not None:
        active_escalation = await escalation_repository.get_active_by_ticket_id(
            ticket.ticket_id
        )
        if active_escalation is not None:
            if escalation_handling_sla_repository is not None:
                accepted = (
                    await escalation_handling_sla_repository.get_by_escalation_id(
                        active_escalation.escalation_id
                    )
                    is not None
                )
                frozen = not accepted
            else:
                frozen = active_escalation.status == EscalationStatus.ACTIVE

            if frozen:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "This ticket has been escalated and is awaiting "
                        "acknowledgment and assignment — it cannot be worked "
                        "until a supervisor acknowledges and assigns it."
                    ),
                )

    if ticket.agent_id == current_user.user_id:
        if has_permission(current_user, "ticket:editown_ticket"):
            return
    elif has_permission_for_ticket(
        current_user, "ticket:editother_ticket", ticket.ticket_id
    ):
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


def ensure_can_compose_for_client(client, current_user: User) -> None:
    """
    Gates POST /inbox/compose — who may author a brand-new outbound
    email (no prior inbound message) to one of the platform's
    clients. Mirrors ensure_agent_can_view_pending_interaction's
    ownership rule (Site Lead/Super Admin unrestricted, Account
    Manager only their own clients), since starting a new pre-ticket
    thread is the same kind of "own this client's mail" action as
    claiming/archiving/snoozing one. Team Lead/Staff are deliberately
    excluded — they only ever work already-ticketed mail, scoped by
    category/assignment, and have no pre-ticket client-ownership
    concept to compose into.
    """

    if current_user.role.name in GLOBAL_INBOX_ROLE_NAMES:
        return

    if (
        current_user.role.name == ACCOUNT_MANAGER_ROLE_NAME
        and client.account_manager_id == current_user.user_id
    ):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to compose mail for this client.",
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


def has_permission_for_ticket(
    current_user: User,
    permission_name: str,
    ticket_id,
) -> bool:
    """
    Like has_permission, but also true if the permission was granted
    scoped to this one specific ticket (see rbac-service's
    scope_ticket_id on UserPermissionOverride/PermissionRequest and
    the JWT's separate `scoped_permissions` claim) — a Staff member
    approved for ticket:editother_ticket on exactly one teammate's
    ticket never reads as holding it everywhere via has_permission,
    only as holding it for that ticket_id here.
    """

    if has_permission(current_user, permission_name):
        return True

    scoped = getattr(current_user, "scoped_permissions", None) or {}

    return str(ticket_id) in scoped.get(permission_name, [])


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
    ticket:editother_ticket themselves — the same permission that lets
    someone bypass ensure_agent_can_act_on_ticket's non-owner check,
    so only someone who could already act on any other ticket in scope
    can decide to let someone else in too. Deliberately the unscoped
    check (has_permission, not has_permission_for_ticket) — a Staff
    member holding a one-ticket-scoped grant on ticket A can't use
    that to start reviewing edit-access requests on ticket B.
    """

    ensure_agent_can_view_ticket(ticket, current_user)
    ensure_has_permission(current_user, "ticket:editother_ticket")


# Roles that bypass ticket:close_ticket/ticket:reopen unconditionally,
# per the approved RBAC permission matrix — deliberately narrower than
# SUPERVISOR_ROLE_NAMES. Unlike ticket:transfer/ticket:assign (where
# Team Lead is Full-by-default, team-scoped), the matrix marks Team
# Lead as Override-only for closing/reopening — closing a ticket ends
# its Resolution SLA clock and is meant to be a deliberate, narrower
# gate than ordinary team supervision. Account Manager is NOT in this
# bypass set either: they get Full access via the ticket:close_ticket/
# ticket:reopen permission itself (granted by default in seed.py),
# scoped to their own clients by the separate
# ensure_account_manager_owns_ticket_client check the calling method
# also runs — not a blanket role bypass.
CLOSE_REOPEN_BYPASS_ROLE_NAMES = {"Site Lead", "Super Admin"}


def ensure_can_close_ticket(current_user: User) -> None:
    """
    Gates the dedicated Close Ticket action
    (InteractionService.close_ticket) — added specifically so the
    Resolution SLA's "ends only when a Manager verifies and closes"
    requirement is actually true rather than aspirational: without
    this gate, an agent could otherwise silently end the SLA clock
    with no manager involved at all. Moving to RESOLVED (an agent's
    own proposed fix) is unaffected by this gate and remains open to
    whoever could already change status.

    Only Site Lead/Super Admin bypass unconditionally (see
    CLOSE_REOPEN_BYPASS_ROLE_NAMES's own docstring for why this is
    narrower than SUPERVISOR_ROLE_NAMES) — everyone else, including
    Account Manager and Team Lead, falls through to the
    ticket:close_ticket permission check. Account Manager holds it by
    default (own clients, enforced separately); Team Lead/Staff need a
    personal override.
    """

    if current_user.role.name in CLOSE_REOPEN_BYPASS_ROLE_NAMES:
        return

    ensure_has_permission(current_user, "ticket:close_ticket")


def ensure_can_reopen_ticket(current_user: User) -> None:
    """
    Gates the dedicated Reopen Ticket action
    (InteractionService.reopen_ticket) — mirrors ensure_can_close_ticket
    exactly (see CLOSE_REOPEN_BYPASS_ROLE_NAMES), since reopening undoes
    the same close a supervisor was required to perform in the first
    place.
    """

    if current_user.role.name in CLOSE_REOPEN_BYPASS_ROLE_NAMES:
        return

    ensure_has_permission(current_user, "ticket:reopen")


def ensure_can_override_sla(current_user: User) -> None:
    """
    Gates the manual SLA pause/resume override action — the real,
    per-ticket enforcement point for ticket:change_sla (the RBAC matrix
    doc's own resolution for that otherwise-dead permission: "wire it
    to the per-ticket SLA-target-adjustment action"). Only Site Lead/
    Super Admin bypass unconditionally — same narrower-than-
    SUPERVISOR_ROLE_NAMES shape as ensure_can_close_ticket/
    ensure_can_reopen_ticket, and for the same reason: Account Manager
    gets Full access via holding ticket:change_sla by role default
    (seed.py), scoped to their own clients by the caller's separate
    ensure_account_manager_owns_ticket_client check, not a blanket
    bypass; Team Lead/Staff fall through to the same permission check,
    Override-only per the doc (unlike SUPERVISOR_ROLE_NAMES's blanket
    Team Lead bypass used elsewhere for transfer/assign).
    """

    if current_user.role.name in GLOBAL_INBOX_ROLE_NAMES:
        return

    ensure_has_permission(current_user, "ticket:change_sla")


def ensure_can_manage_sla_policies(current_user: User) -> None:
    """
    SLA targets are company-wide contractual/operational settings, not
    per-team — restricted to Site Lead/Super Admin specifically
    (narrower than SUPERVISOR_ROLE_NAMES, which also includes Team
    Lead/Account Manager) via the sla:manage_policies permission.
    """

    ensure_has_permission(current_user, "sla:manage_policies")


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

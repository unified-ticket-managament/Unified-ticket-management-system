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

# The remaining four role-name literals, centralized here so every
# module that needs one imports it instead of re-declaring its own
# local copy of the same string (previously independently redeclared
# in both assignment_service.py and sla_escalation_rules.py — harmless
# today since every copy happened to agree, but a real "single source
# of truth" risk the moment one of them drifts, e.g. a role rename).
# assignment_service.py and sla_escalation_rules.py both now import
# from here instead of declaring their own, so anything that used to
# import these names from either of those two modules keeps working
# unchanged — they're re-exported, not removed.
TEAM_LEAD_ROLE_NAME = "Team Lead"
STAFF_ROLE_NAME = "Staff"
SITE_LEAD_ROLE_NAME = "Site Lead"
SUPER_ADMIN_ROLE_NAME = "Super Admin"

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


def resolve_status_after_assignment(
    current_status: TicketStatus,
) -> TicketStatus | None:
    """
    The single, shared rule for "does an assignment change the
    ticket's status": if `current_status` is OPEN, the ticket moves to
    IN_PROGRESS — otherwise (already IN_PROGRESS, WAITING_FOR_CLIENT,
    PENDING, RESOLVED, or CLOSED) nothing changes. Returns the new
    status, or None when no change should happen, so every caller can
    write the same `if new_status is not None: ...` pattern instead of
    re-deriving the OPEN check itself.

    Deliberately keyed on `current_status` alone — never on who the
    new assignee is or what role they hold. Assigning a ticket to
    Staff, a Team Lead, an Account Manager, a Site Lead, Super Admin,
    or an agent claiming it for themselves are all the same event as
    far as this rule is concerned: someone is now actually working the
    ticket, so it should never sit at OPEN afterward. This is what
    every assignment path (InteractionService.transfer_agent,
    TicketRepository.claim, InboxTicketService.create_ticket_from_interaction's
    pre-assignment) must call instead of re-implementing its own
    OPEN-check, so the rule can never silently diverge between paths.
    """

    if current_status == TicketStatus.OPEN:
        return TicketStatus.IN_PROGRESS

    return None


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

    Requires membership in AGENT_ROLE_NAMES before anything else — a
    real, confirmed gap found during an RBAC verification pass: this
    function used to return (unrestricted) for ANY role outside
    CATEGORY_SCOPED_ROLE_NAMES, which was meant to cover "Account
    Manager/Site Lead/Super Admin stay unrestricted" but actually also
    silently let Viewer (the client-facing role, deliberately excluded
    from AGENT_ROLE_NAMES everywhere else — e.g. get_current_agent)
    through unrestricted too, since Viewer isn't in
    CATEGORY_SCOPED_ROLE_NAMES either. Every real ticket-mutating
    action already reaches this same function first, so this one
    check now closes the gap everywhere at once rather than needing a
    separate fix per call site.
    """

    if current_user.role.name not in AGENT_ROLE_NAMES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this ticket.",
        )

    if current_user.role.name not in CATEGORY_SCOPED_ROLE_NAMES:
        return

    # A ticket-scoped ticket:editother_ticket override (granted via an
    # approved RBAC Permission Request — see PermissionRequestService/
    # PermissionOverrideService.grant) authorizes a Team Lead/Staff
    # member to view and act on exactly this one ticket regardless of
    # their own category — the whole point of that grant is crossing
    # category/ownership boundaries for one specific ticket, so the
    # category gate below must not re-block it. Mirrors the existing
    # has_permission_for_ticket check ensure_agent_can_act_on_ticket
    # already runs for the *action* side of this same scenario.
    if has_permission_for_ticket(current_user, "ticket:editother_ticket", ticket.ticket_id):
        return

    user_category_names = {
        c.category_name for c in getattr(current_user, "categories", None) or []
    }

    if ticket.ticket_type not in user_category_names:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this ticket.",
        )


async def ensure_ticket_not_frozen_by_escalation(
    ticket: Ticket,
    escalation_repository=None,
    escalation_handling_sla_repository=None,
) -> None:
    """
    Raises 403 if `ticket` has a non-CLOSED escalation that hasn't yet
    been *accepted* (acknowledged AND assigned — see
    EscalationService._complete_acceptance) — for **everyone**,
    including supervisors, since every possible escalation owner
    (TicketEscalation.owner_ids can only ever name a Team Lead/Account
    Manager/Site Lead/Super Admin) is itself a supervisor. Extracted
    out of ensure_agent_can_act_on_ticket (which still calls this first,
    before its own supervisor bypass) so a caller that deliberately
    skips that function's ownership/editother_ticket check — today,
    only InteractionService.change_priority, which intentionally lets
    any ticket:change_priority holder act on any ticket in their
    visibility scope, not just an assigned one — can still apply this
    one, narrower rule without also gaining the ownership restriction
    it doesn't want.

    Whether acceptance has completed is read off the EscalationHandlingSLA
    table (`escalation_handling_sla_repository`, optional): a row exists
    for an escalation_id if and only if _complete_acceptance has already
    run for it. Falls back to the coarser "frozen only while status is
    still ACTIVE" rule if that repository isn't supplied, so a caller
    passing only `escalation_repository` still gets a safe (if slightly
    less precise) check rather than none at all. `escalation_repository`
    is optional — a caller that omits it skips this check entirely
    (a plain no-op, not a bypass an attacker could trigger, since only
    the caller's own code decides whether to pass it).
    """

    if escalation_repository is None:
        return

    active_escalation = await escalation_repository.get_active_by_ticket_id(
        ticket.ticket_id
    )
    if active_escalation is None:
        return

    if escalation_handling_sla_repository is not None:
        # Any row at all — active or already-breached-and-superseded —
        # means acceptance has happened at least once for this
        # escalation; that's what unfreezes the previous owner,
        # regardless of whether the level has since advanced again.
        accepted = (
            await escalation_handling_sla_repository.get_latest_by_escalation_id(
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


async def ensure_agent_can_act_on_ticket(
    ticket: Ticket,
    current_user: User,
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

    A non-CLOSED escalated ticket is frozen for **everyone** — the
    previous assignee and the new escalation owner alike, supervisors
    included — until the escalation has actually been *accepted*, not
    merely acknowledged. This check therefore now runs before the
    supervisor bypass below, not after it: every possible escalation
    owner (TicketEscalation.owner_ids can only ever name a Team
    Lead/Account Manager/Site Lead/Super Admin — see
    EscalationService._resolve_owners_for_level) is itself a
    supervisor, so checking the freeze after the bypass made it
    unreachable for exactly the population it exists to restrict — a
    real, confirmed bug (a Team Lead a ticket just escalated to could
    reply/change status/upload attachments/close the ticket immediately,
    before ever clicking Acknowledge). Acknowledging alone
    (EscalationService.acknowledge) only stops the ack-window
    auto-advance; the Resolution SLA (and this freeze) only lift once a
    supervisor has *also* assigned the ticket to someone (claim/
    transfer/confirm-unchanged — see
    EscalationService._complete_acceptance), matching "Resolution SLA
    starts only after Acknowledge AND Assign." Whether acceptance has
    completed is read off the EscalationHandlingSLA table
    (`escalation_handling_sla_repository`, optional): a row exists for
    an escalation_id if and only if _complete_acceptance has already
    run for it (it's the one and only place that row gets created) —
    reusing that existing fact rather than adding a new column. If
    `escalation_handling_sla_repository` isn't supplied, this falls
    back to the older, coarser rule (frozen only while status is
    still ACTIVE i.e. never acknowledged at all) so existing callers
    that haven't been updated to pass it keep their prior behavior
    rather than becoming newly, incorrectly frozen forever.
    `escalation_repository` is optional — callers that don't pass one
    simply skip this check entirely. Acknowledge/claim_ticket/
    transfer_agent/confirm_assignment — the only ways this freeze ever
    lifts — all have their own, separate authorization (owner_ids
    membership, or the supervisor-only ensure_can_reassign_ticket) and
    never call this function, so none of them are affected by the
    freeze they exist to resolve.

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
    touching every other ticket in scope).

    Deliberately NOT applied to claim_ticket (picking up an unclaimed
    ticket is how you become its assigned agent in the first place)
    or transfer_agent (already gated by ensure_can_reassign_ticket,
    which is supervisor-only regardless of current assignment).
    """

    ensure_agent_can_view_ticket(ticket, current_user)

    await ensure_ticket_not_frozen_by_escalation(
        ticket, escalation_repository, escalation_handling_sla_repository
    )

    if current_user.role.name in SUPERVISOR_ROLE_NAMES:
        return

    if ticket.agent_id == current_user.user_id:
        if has_permission(current_user, "ticket:editown_ticket"):
            return
    elif has_permission_for_ticket(
        current_user, "ticket:editother_ticket", ticket.ticket_id
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


async def ensure_agent_can_view_ticket_including_escalated(
    ticket: Ticket,
    current_user: User,
    client_repository,
    escalation_repository=None,
) -> bool:
    """
    Same gate as ensure_agent_can_view_ticket + ensure_account_manager_owns_
    ticket_client, with the one additional escape hatch ticket_service.
    get_by_id already applies to the ticket-detail read itself: a caller
    holding ticket:view_escalated may also view this ticket's read-only
    sub-resources (timeline, attachments, audit logs, SLA/escalation
    state) whenever it currently has an active (non-CLOSED) escalation,
    regardless of category/client-ownership scoping. `escalation_repository`
    is optional — a caller that omits it just never gets the widening
    (falls through to the ordinary, narrower check), matching this file's
    existing "optional repository -> narrower fallback, never a bypass"
    idiom.

    Returns True when access was granted purely via the escalation
    override, so a caller with an additional permission check of its own
    (e.g. get_ticket_audit_logs' ticket:view_audit_trail) can decide
    whether to also skip that check for this one escalated ticket.
    """

    if escalation_repository is not None and has_permission(
        current_user, "ticket:view_escalated"
    ):
        escalation = await escalation_repository.get_active_by_ticket_id(
            ticket.ticket_id
        )
        if escalation is not None:
            return True

    ensure_agent_can_view_ticket(ticket, current_user)
    await ensure_account_manager_owns_ticket_client(
        ticket, current_user, client_repository
    )
    return False


async def ensure_agent_can_view_pending_interaction(
    interaction,
    current_user: User,
    client_repository,
    *,
    view_only: bool = False,
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
    "can act on it" and "can see it" stay the same rule — except for
    the `view_only` escape hatch below, which deliberately only
    applies to the "can see it" side.

    `view_only=True` (passed only by OpenEmailService.get_email_details,
    never by any of InteractionService's action call sites) additionally
    admits anyone holding `communication:view_all` — the same permission
    InboxService.get_inbox already gates the list view on for Super
    Admin/Site Lead/Account Manager. Without this, a manager forwarding
    a still-pending mail item to an internal user (
    InteractionService.forward_to_internal_user, delivered via a
    MAIL_FORWARDED Notification rather than the normal scoped inbox
    query) handed that recipient a link to an item this function would
    otherwise always 403 for them on — Staff/Team Lead were never in
    scope here at all, and granting the permission through RBAC's
    Manage-Permissions editor had no effect, since this check was
    purely role/ownership-based with no permission read anywhere in it.
    This intentionally does not widen the *action* call sites (claim/
    archive/snooze/tags/folder/drafts/forward/reply) — holding
    communication:view_all lets a role open and read a pending item
    it was sent, not act on someone else's.
    """

    if current_user.role.name in GLOBAL_INBOX_ROLE_NAMES:
        return

    if view_only and has_permission(current_user, "communication:view_all"):
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
    clients. `communication:reply_external` (RBAC's own Manage-
    Permissions editor — the same permission Reply/Reply All on an
    already-ticketed message already gate on, see
    MessageDetailsView.tsx's canReplyExternal) is the source of truth
    for whether a role/user may compose external mail at all; this
    used to be a hardcoded role-name check (Site Lead/Super Admin
    unconditionally, Account Manager only their own clients, every
    other role — including a Team Lead explicitly granted the
    permission — unconditionally denied), which meant granting the
    permission through the RBAC UI had no effect here.

    Business ownership stays exactly as before on top of the
    permission check: Site Lead/Super Admin remain unrestricted,
    Account Manager stays scoped to their own clients (this is a data-
    ownership rule, not a permission gap, so it isn't satisfied by
    holding the permission alone). Any other role holding the
    permission (e.g. Team Lead) is unrestricted like Site Lead/Super
    Admin — Compose has no per-role client-ownership concept outside
    Account Manager's own-clients rule.
    """

    ensure_has_permission(current_user, "communication:reply_external")

    if current_user.role.name in GLOBAL_INBOX_ROLE_NAMES:
        return

    if current_user.role.name == ACCOUNT_MANAGER_ROLE_NAME:
        if client.account_manager_id == current_user.user_id:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to compose mail for this client.",
        )

    return


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


def ensure_can_view_client_details(current_user: User) -> None:
    """
    Gates GET /clients/{client_id}/details — the Roles page's Client-
    tab expand action ONLY. Deliberately NOT applied to GET /clients
    (list) or GET /clients/{id}/contacts, which stay ungated: both are
    shared by Mail Compose's client dropdown, the Mail filter dropdown,
    the Rules engine's client picker, "Create Dummy Mail", and (the
    contacts route specifically) the Create/Edit User dialog's own
    Client-role contact-email prefill (user-form-dialog.tsx) — none of
    which client:view is meant to touch, and gating either shared
    route would break all of them.

    This exists as a compensating control alongside RBAC's own
    GET /roles/{role_id}/users widening from a hardcoded role
    allow-list to a plain user:view check (see
    app.rbac.api.v1.roles.list_users_for_role) — that widening also
    opened the Roles page itself to Team Lead/Staff/Client for the
    first time, and this permission is what stops those roles from
    also seeing this page's Client-tab organization email/account
    manager/contact details, which Super Admin/Site Lead/Account
    Manager already saw unrestricted before.
    """

    ensure_has_permission(current_user, "client:view")


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

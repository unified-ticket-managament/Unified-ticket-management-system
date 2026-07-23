from dataclasses import dataclass, field
from uuid import UUID

from shared_models.models import User

from app.ticketing.models.client import Client
# Imported from the centralized access_control.py rather than declared
# locally (this module used to declare its own copy) — re-exported
# under the same name, so escalation_service.py's existing
# `from app.ticketing.services.sla_escalation_rules import TEAM_LEAD_ROLE_NAME`
# keeps working unchanged.
from app.ticketing.services.access_control import TEAM_LEAD_ROLE_NAME

#sla_escalation_rules.py

# ---------------------------------------------------------------------
# Threshold ladder — ordered so a single elapsed_fraction reading yields
# every threshold it has crossed, oldest first (a clock discovered at
# 160% fires HALF_ELAPSED, AT_RISK, BREACHED, and ESCALATED all in the
# same tick — each is its own idempotent row via SLABreachNotification's
# unique index, so this is safe even if a prior tick already recorded
# the earlier ones).
# ---------------------------------------------------------------------

THRESHOLDS = (
    ("HALF_ELAPSED", 0.5),
    ("AT_RISK", 0.8),
    ("BREACHED", 1.0),
    ("ESCALATED", 1.5),
)


def thresholds_reached(
    elapsed_fraction: float,
    *,
    half_elapsed: float = 0.5,
    at_risk: float = 0.8,
) -> list[str]:
    """
    Pure classification — every named threshold `elapsed_fraction` has
    met or passed. `half_elapsed`/`at_risk` default to the same 0.5/0.8
    every clock used before per-priority "Warning 1"/"Warning 2"
    cutoffs existed (SLAPolicy.warning_1_percentage/warning_2_percentage,
    see the admin-facing SLA Timing Matrix) — callers with a resolved
    policy pass those in instead. BREACHED (1.0) and ESCALATED (1.5)
    stay fixed globally; only the two warning tiers are configurable.
    """

    cutoffs = (
        ("HALF_ELAPSED", half_elapsed),
        ("AT_RISK", at_risk),
        ("BREACHED", 1.0),
        ("ESCALATED", 1.5),
    )
    return [name for name, cutoff in cutoffs if elapsed_fraction >= cutoff]


# ---------------------------------------------------------------------
# Recipient roles + declarative rule tables — single source of truth
# for "who gets notified at which threshold." Adding/changing a tier's
# recipients is a one-line edit here, not a change to the sweep loop.
# Plain string constants (not a Python/Postgres enum), matching
# NotificationType's own style in app/notifications/service.py — this
# never touches the database, so there's no reason to reach for a
# heavier construct.
# ---------------------------------------------------------------------


class RecipientRole:
    ACCOUNT_MANAGER = "ACCOUNT_MANAGER"
    TEAM_LEAD = "TEAM_LEAD"
    TEAM_MEMBERS = "TEAM_MEMBERS"
    ASSIGNED_AGENT = "ASSIGNED_AGENT"
    GLOBAL_INBOX = "GLOBAL_INBOX"
    CURRENT_OWNER = "CURRENT_OWNER"


FIRST_RESPONSE_RULES: dict[str, tuple[str, ...]] = {
    "HALF_ELAPSED": (RecipientRole.ACCOUNT_MANAGER,),
    "AT_RISK": (RecipientRole.ACCOUNT_MANAGER,),
    "BREACHED": (RecipientRole.ACCOUNT_MANAGER, RecipientRole.GLOBAL_INBOX),
    "ESCALATED": (RecipientRole.ACCOUNT_MANAGER, RecipientRole.GLOBAL_INBOX),
}

# Half-Elapsed/At-Risk/Breached: resolve to whoever is actually working
# the ticket right now — the assigned agent (claimed), the escalation's
# current owner (escalated), or the category's Team Lead+staff pool
# (unclaimed) — rather than a role ladder. A ticket's higher-ups only
# ever learn about it through the escalation workflow's own
# hierarchical notifications (EscalationService._notify_owners),
# triggered separately when an escalation is created/advances.
#
# ESCALATED (150% elapsed) has no entry here at all, deliberately —
# SLASweepService._notify_resolution skips notification entirely at
# that tier. The old CLAIMED/UNCLAIMED role-ladder tables this
# threshold used to consult (RESOLUTION_RULES_CLAIMED/UNCLAIMED) were
# removed outright: 150% is the exact crossing that creates the
# TicketEscalation (see run_sweep's classification loop — deliberately
# not BREACHED/100%, so the current owner's own Breached notification
# at 100% isn't pre-empted by an ownership handoff), so the real
# escalation-created notification has already informed the actual
# owner earlier in this same tick — a second, generic "Resolution SLA
# Escalated" notification on top of that would be pure noise, not a
# second real signal.
RESOLUTION_RULES_CURRENT_OWNER: dict[str, tuple[str, ...]] = {
    "HALF_ELAPSED": (RecipientRole.CURRENT_OWNER,),
    "AT_RISK": (RecipientRole.CURRENT_OWNER,),
    "BREACHED": (RecipientRole.CURRENT_OWNER,),
}

@dataclass
class RecipientContext:
    """
    Per-clock data needed to resolve a threshold's recipient set — narrow
    and concrete on purpose (only fields resolvers actually consume), not
    a generic/open-ended bag. `assigned_agent` is populated only for a
    claimed Resolution clock; `team_leads`/`team_members` only for an
    unclaimed one; First Response clocks only ever need `client` and
    `global_inbox_ids`.
    """

    client: Client | None = None
    assigned_agent: User | None = None
    team_leads: list[User] = field(default_factory=list)
    team_members: list[User] = field(default_factory=list)
    global_inbox_ids: set[UUID] = field(default_factory=set)
    # The ticket's active TicketEscalation.owner_ids, if any — the
    # "lower-level" owner it currently sits with (e.g. Team Lead), used
    # by resolve_current_owner below to take priority over
    # assigned_agent/team_leads while an escalation is awaiting
    # acceptance.
    escalation_owner_ids: set[UUID] = field(default_factory=set)

    # Whether the active escalation's current level has already
    # completed acceptance (accept -> assign settled — see
    # EscalationService._complete_acceptance) rather than merely being
    # ACTIVE/ACKNOWLEDGED-but-unassigned. Mirrors
    # TicketEscalation.handling_stage_due_at being non-null (the same
    # signal EscalationService itself uses to decide whether a handling
    # stage is currently running). Only meaningful when
    # escalation_owner_ids is non-empty; ignored otherwise.
    escalation_acceptance_completed: bool = False


def resolve_account_manager(ctx: RecipientContext) -> set[UUID]:
    """
    The client-owning Account Manager (`clients.account_manager_id`,
    NOT nullable) — guarded on `ctx.client is None`, since it's the
    *link* to a client (ResolutionSLA.client_id / FirstResponseSLA.
    client_id / Ticket.client_company_id) that's nullable, never
    account_manager_id itself once a Client row exists.
    """

    if ctx.client is None:
        return set()
    return {ctx.client.account_manager_id}


def resolve_team_lead(ctx: RecipientContext) -> set[UUID]:
    """
    Claimed case: the assigned agent's own Team Lead (`teamlead_id`) if
    they're Staff; if they self-claimed as a Team Lead, they satisfy
    this role themselves; any other self-claimer (Account Manager, Site
    Lead, Super Admin — all reachable, since claim_ticket applies no
    category gate) resolves to nobody extra here.

    Unclaimed case: every Team Lead resolved for the ticket's category.

    `ctx.assigned_agent` is only ever populated for the claimed case, so
    checking it first is enough to pick the right branch without an
    explicit case flag.
    """

    if ctx.assigned_agent is not None:
        if ctx.assigned_agent.teamlead_id is not None:
            return {ctx.assigned_agent.teamlead_id}
        if ctx.assigned_agent.role.name == TEAM_LEAD_ROLE_NAME:
            return {ctx.assigned_agent.user_id}
        return set()

    return {u.user_id for u in ctx.team_leads}


def resolve_team_members(ctx: RecipientContext) -> set[UUID]:
    return {u.user_id for u in ctx.team_members}


def resolve_assigned_agent(ctx: RecipientContext) -> set[UUID]:
    if ctx.assigned_agent is None:
        return set()
    return {ctx.assigned_agent.user_id}


def resolve_global_inbox(ctx: RecipientContext) -> set[UUID]:
    # Precomputed once per sweep run (Site Lead + Super Admin never vary
    # per-clock) — see SLASweepService._global_inbox_user_ids.
    return ctx.global_inbox_ids


def resolve_current_owner(ctx: RecipientContext) -> set[UUID]:
    """
    Whoever is actually working the ticket right now.

    While an escalation is awaiting acceptance (ACTIVE, or ACKNOWLEDGED
    but not yet assigned to anyone) its owner_ids — the accountable
    acknowledger, e.g. a Team Lead — takes priority, since nobody has
    actually taken the ticket on yet. Once acceptance completes
    (escalation_acceptance_completed — the supervisor has claimed,
    transferred, or confirmed an assignee), that assignee is the one
    genuinely doing the work and the one on the hook for the new,
    tighter handling-stage deadline — so `assigned_agent` (ticket.
    agent_id, resolved fresh every sweep tick, never the escalation's
    own stale owner_ids) takes over.

    This was a real bug, not a hypothetical one: TicketEscalation.
    owner_ids is only ever rewritten by an explicit ladder advance
    (TicketEscalationRepository.advance — the ack-timeout or
    handling-SLA-breach paths); a plain accept-and-assign
    (EscalationService._complete_acceptance, reached from
    claim_ticket/transfer_agent/confirm_assignment) never touches it.
    Without this split, every Resolution SLA notification kept going to
    whoever last acknowledged the escalation, even long after they'd
    handed the ticket to someone else.

    Absent any active escalation at all, this is just the plain
    assigned agent (claimed) or the category's Team Lead + staff pool
    (unclaimed) — today's un-escalated baseline, with no
    ladder-climbing on top.
    """

    if ctx.escalation_owner_ids and not ctx.escalation_acceptance_completed:
        return ctx.escalation_owner_ids
    if ctx.assigned_agent is not None:
        return resolve_assigned_agent(ctx)
    if ctx.escalation_owner_ids:
        return ctx.escalation_owner_ids
    return resolve_team_lead(ctx) | resolve_team_members(ctx)


RECIPIENT_RESOLVERS = {
    RecipientRole.ACCOUNT_MANAGER: resolve_account_manager,
    RecipientRole.TEAM_LEAD: resolve_team_lead,
    RecipientRole.TEAM_MEMBERS: resolve_team_members,
    RecipientRole.ASSIGNED_AGENT: resolve_assigned_agent,
    RecipientRole.GLOBAL_INBOX: resolve_global_inbox,
    RecipientRole.CURRENT_OWNER: resolve_current_owner,
}


def resolve_recipients(
    rules: dict[str, tuple[str, ...]], threshold: str, ctx: RecipientContext
) -> set[UUID]:
    """
    Looks up `threshold`'s recipient-role tuple in `rules`, resolves
    each role against `ctx`, and unions the results. Returns an empty
    set for a threshold with no rule entry rather than raising — the
    sweep should never crash because a rule table is momentarily out of
    sync with THRESHOLDS during a future edit.
    """

    recipients: set[UUID] = set()
    for role in rules.get(threshold, ()):
        recipients |= RECIPIENT_RESOLVERS[role](ctx)
    return recipients

from uuid import UUID

from shared_models.models import User

from app.ticketing.enums import EscalationLevel

#escalation_rules.py

# Ownership chain a TicketEscalation climbs if ignored — Agent is the
# un-escalated baseline (not a level of its own, never appears here);
# SITE_LEAD is terminal. Deliberately separate from sla_escalation_
# rules.py's RecipientRole/THRESHOLDS ladder: that one only ever widens
# who gets *notified* as a Resolution SLA clock ages, and never changes
# who *owns* follow-up — this chain is the reverse, ownership only,
# independent of elapsed-time thresholds.
ESCALATION_LEVEL_ORDER: tuple[EscalationLevel, ...] = (
    EscalationLevel.TEAM_LEAD,
    EscalationLevel.MANAGER,
    EscalationLevel.SITE_LEAD,
)


def next_level(current: EscalationLevel | None) -> EscalationLevel | None:
    """
    `current=None` (no escalation exists yet) always starts at
    TEAM_LEAD. Returns None once already at the terminal SITE_LEAD
    level — the caller's job to interpret that as "re-notify the same
    owners" rather than raising or silently stalling.
    """

    if current is None:
        return ESCALATION_LEVEL_ORDER[0]

    index = ESCALATION_LEVEL_ORDER.index(current)
    if index + 1 >= len(ESCALATION_LEVEL_ORDER):
        return None

    return ESCALATION_LEVEL_ORDER[index + 1]


def resolve_manager_ids(users: list[User]) -> set[UUID]:
    """
    The MANAGER level's owner set: every distinct `manager_id` among
    the given (already-loaded) users — typically the TEAM_LEAD level's
    just-resolved owners, one hop up the existing `manager_id` self-FK
    org-reporting-line (see shared_models.models.User), NOT
    sla_escalation_rules.RecipientRole.ACCOUNT_MANAGER (a different
    concept entirely: client ownership via Client.account_manager_id,
    unrelated to the reporting hierarchy). A user with no manager_id
    set (data gap, or they report to nobody) simply contributes
    nothing — same "resolves to nobody rather than raising" convention
    as every resolver in sla_escalation_rules.py.
    """

    return {u.manager_id for u in users if u.manager_id is not None}

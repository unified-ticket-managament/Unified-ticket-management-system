from enum import Enum

#escalation_enums.py
class EscalationLevel(str, Enum):
    """
    Internal escalation ownership chain — deliberately separate from
    the Resolution SLA's own recipient ladder (sla_escalation_rules.py's
    RecipientRole), which only ever widens who gets *notified* at a
    threshold and never changes who *owns* the ticket.

    TEAM_LEAD/MANAGER are retired role-ladder values, kept only so old
    rows still deserialize — nothing writes them anymore. Escalation
    routing now follows the ticket's own assignment history (see
    escalation_rules.build_chain_owner_ids/resolve_owners_for_chain):
    every non-terminal step is ASSIGNMENT_CHAIN, and SITE_LEAD stays a
    real, literal terminal marker — either the chain is genuinely
    exhausted, or nobody in it could be resolved at all — at which
    point Site Lead/Super Admin become the owners and an overdue
    acknowledgment there just re-notifies the same owners rather than
    advancing further.
    """

    TEAM_LEAD = "TEAM_LEAD"
    MANAGER = "MANAGER"
    ASSIGNMENT_CHAIN = "ASSIGNMENT_CHAIN"
    SITE_LEAD = "SITE_LEAD"


class EscalationStatus(str, Enum):
    """
    Lifecycle of one TicketEscalation row. ACTIVE means the current
    level's owner(s) haven't acknowledged yet (and are subject to
    auto-advance once ack_due_at passes); ACKNOWLEDGED means they have,
    and the escalation stays parked at that level until the ticket is
    resolved (no further auto-advance); CLOSED is terminal, set only
    when the underlying Resolution SLA completes (or a supervisor
    manually closes it) — never reopened.
    """

    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLOSED = "CLOSED"


# Plain string constants (not a Postgres enum) for `triggered_by` and
# `closed_reason` — same lighter-weight convention this codebase already
# uses for SLABreachNotification.clock_type/threshold and
# FirstResponseSLA.completion_reason, both descriptive metadata rather
# than a state machine needing DB-level enforcement.
TRIGGERED_BY_MANUAL = "MANUAL"
TRIGGERED_BY_AUTO_SLA_BREACH = "AUTO_SLA_BREACH"

CLOSED_REASON_TICKET_RESOLVED = "TICKET_RESOLVED"
CLOSED_REASON_MANUALLY_CLOSED = "MANUALLY_CLOSED"

# TicketEscalation.owner_roles values — per-owner tag alongside the
# flat owner_ids set, used for exactly one thing: whether that owner
# may Assign a ticket to themselves when Acknowledging (see
# EscalationService.get_acknowledge_candidates and
# InteractionService.acknowledge_and_assign_escalation). owner_ids
# membership itself (who may Acknowledge/Confirm/manually escalate at
# all) is unaffected by this tag.
OWNER_ROLE_ASSIGNEE_CHAIN = "ASSIGNEE_CHAIN"
OWNER_ROLE_REPORTING_MANAGER = "REPORTING_MANAGER"
OWNER_ROLE_SITE_LEAD_FALLBACK = "SITE_LEAD_FALLBACK"

from enum import Enum

#escalation_enums.py
class EscalationLevel(str, Enum):
    """
    Internal escalation ownership chain — deliberately separate from
    the Resolution SLA's own recipient ladder (sla_escalation_rules.py's
    RecipientRole), which only ever widens who gets *notified* at a
    threshold and never changes who *owns* the ticket. TEAM_LEAD is
    always the first level a TicketEscalation is created at (an Agent
    is the un-escalated baseline, not a level of its own); SITE_LEAD is
    terminal — an overdue acknowledgment at that level just re-notifies
    the same owners rather than advancing further.
    """

    TEAM_LEAD = "TEAM_LEAD"
    MANAGER = "MANAGER"
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

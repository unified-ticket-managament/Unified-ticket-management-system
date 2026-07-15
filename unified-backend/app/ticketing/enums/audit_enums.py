from enum import Enum

#audit_enums.py
class AuditEntityType(str, Enum):
    """
    The kind of entity an audit_logs row is about.
    """

    TICKET = "TICKET"
    INTERACTION = "INTERACTION"
    ATTACHMENT = "ATTACHMENT"
    CLIENT = "CLIENT"
    USER = "USER"


class AuditEventType(str, Enum):
    """
    What happened to the entity. Not a closed 1:1 mapping to
    entity_type — e.g. NOTE_ADDED / REPLY_ADDED / INTERACTION_HIDDEN
    are all INTERACTION events, ATTACHMENT_UPLOADED is an ATTACHMENT
    event, and the rest are TICKET events.
    """

    TICKET_CREATED = "TICKET_CREATED"
    TICKET_UPDATED = "TICKET_UPDATED"
    TICKET_RESOLVED = "TICKET_RESOLVED"
    STATUS_CHANGED = "STATUS_CHANGED"
    PRIORITY_CHANGED = "PRIORITY_CHANGED"
    AGENT_TRANSFERRED = "AGENT_TRANSFERRED"
    # Closing/reopening used to be logged as a generic STATUS_CHANGED
    # row — these are dedicated events for the new Close Ticket/Reopen
    # Ticket actions (InteractionService.close_ticket/reopen_ticket),
    # distinct from an ordinary status change.
    TICKET_CLOSED = "TICKET_CLOSED"
    TICKET_REOPENED = "TICKET_REOPENED"
    INTERACTION_HIDDEN = "INTERACTION_HIDDEN"
    ATTACHMENT_UPLOADED = "ATTACHMENT_UPLOADED"
    NOTE_ADDED = "NOTE_ADDED"
    REPLY_ADDED = "REPLY_ADDED"
    EMAIL_RECEIVED = "EMAIL_RECEIVED"
    CLIENT_CREATED = "CLIENT_CREATED"
    INTERACTION_CLAIMED = "INTERACTION_CLAIMED"
    INTERACTION_ARCHIVED = "INTERACTION_ARCHIVED"
    INTERACTION_SNOOZED = "INTERACTION_SNOOZED"
    INTERACTION_UNSNOOZED = "INTERACTION_UNSNOOZED"
    INTERACTION_TAGGED = "INTERACTION_TAGGED"
    INTERACTION_FOLDER_CHANGED = "INTERACTION_FOLDER_CHANGED"
    TICKET_RELATED = "TICKET_RELATED"
    TICKET_UNRELATED = "TICKET_UNRELATED"
    TICKET_CLAIMED = "TICKET_CLAIMED"
    EDIT_ACCESS_REQUESTED = "EDIT_ACCESS_REQUESTED"
    EDIT_ACCESS_APPROVED = "EDIT_ACCESS_APPROVED"
    EDIT_ACCESS_REJECTED = "EDIT_ACCESS_REJECTED"
    # Fired whenever the Resolution SLA clock pauses/resumes — the
    # automatic WAITING_FOR_CLIENT-driven case (InteractionService.
    # change_status) as well as a supervisor's manual override
    # (SLAService.manual_pause/manual_resume, tagged "trigger":
    # "manual_override" in new_values to distinguish it).
    SLA_PAUSED = "SLA_PAUSED"
    SLA_RESUMED = "SLA_RESUMED"
    SLA_BREACH_DETECTED = "SLA_BREACH_DETECTED"
    SLA_ESCALATED = "SLA_ESCALATED"
    # Internal escalation workflow (TicketEscalation) — distinct from
    # SLA_ESCALATED above, which is the Resolution SLA's own 1.5x
    # notification-ladder tier and never touches ownership/ack state.
    ESCALATION_CREATED = "ESCALATION_CREATED"
    ESCALATION_ACKNOWLEDGED = "ESCALATION_ACKNOWLEDGED"
    ESCALATION_ADVANCED = "ESCALATION_ADVANCED"
    ESCALATION_CLOSED = "ESCALATION_CLOSED"


class ActorRole(str, Enum):
    """
    Who actually performed the action behind an audit row.

    AGENT — a Staff member acting via the "acting as" identity
    (this app has no real authentication; agent_name is the only
    identity concept, resolved to a real Staff user by name).
    CLIENT — the end user / requester, e.g. an inbound email.
    SYSTEM — anything automatic: no agent_name was given, or it
    didn't resolve to an active Staff member.
    """

    AGENT = "AGENT"
    CLIENT = "CLIENT"
    SYSTEM = "SYSTEM"

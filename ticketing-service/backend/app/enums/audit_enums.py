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

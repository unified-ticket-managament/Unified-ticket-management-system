# email_policy.py

from app.notifications.service import NotificationType

# The single source of truth for "which notification types are
# business-critical enough to also become an email" — every other
# notification type keeps its existing in-app-only behavior (Bell +
# Internal Mail) with zero code changes anywhere else. Add a type here
# to make it email-eligible; remove one to stop emailing it. Nothing
# else in the codebase needs to change either way.
EMAIL_ELIGIBLE_NOTIFICATION_TYPES = frozenset(
    {
        NotificationType.TICKET_ASSIGNED,
        # The internal ownership-chain escalation ("Ticket Escalated:
        # {title}" — see EscalationService), not SLA_ESCALATED (the
        # Resolution SLA notification ladder's own tier) — the two are
        # deliberately distinct concepts elsewhere in this codebase,
        # and only the former matches the "Ticket Escalated" business
        # event this policy is scoped to.
        NotificationType.ESCALATION_CREATED,
        NotificationType.SLA_BREACHED,
        NotificationType.CLIENT_REPLY,
        NotificationType.EDIT_ACCESS_APPROVED,
        NotificationType.EDIT_ACCESS_REJECTED,
    }
)


def is_email_eligible(notification_type: str) -> bool:
    return notification_type in EMAIL_ELIGIBLE_NOTIFICATION_TYPES

# sla_breach_notifier.py

from uuid import UUID

from app.core.config import get_settings
from app.core.email_sender import get_email_sender
from app.notifications.service import NotificationService, NotificationType
from app.ticketing.models.client import Client
from app.ticketing.models.first_response_sla import FirstResponseSLA
from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.access_control import GLOBAL_INBOX_ROLE_NAMES
from app.ticketing.services.sla_escalation_rules import (
    FIRST_RESPONSE_RULES,
    RecipientContext,
    resolve_recipients,
)

# How much of the email's own body to fold into the notification's
# message text — long enough to actually be useful without the
# in-app/System-folder notification list turning into a wall of text.
BODY_SNIPPET_MAX_CHARS = 200


def _first_response_notification_copy(
    *, interaction: Interaction | None, client: Client | None, threshold: str
) -> tuple[str, str]:
    """
    Builds a notification title/message specific to the actual pending
    email — previously a single hardcoded, identical-for-every-email
    string ("An inbound email is still awaiting triage."), which made
    the Mail System folder useless for telling breached emails apart
    without opening each one. Falls back to the old generic wording
    only if the interaction couldn't be loaded (e.g. already deleted).
    """

    threshold_label = threshold.replace("_", " ").title()

    if interaction is None:
        return (
            f"First Response SLA {threshold_label}",
            "An inbound email is still awaiting triage.",
        )

    subject = interaction.subject or "(no subject)"
    client_name = client.name if client is not None else interaction.payload.get("client_name")
    from_name = interaction.payload.get("from_name") or interaction.payload.get("from_email")
    body = (interaction.payload.get("body") or "").strip()
    if len(body) > BODY_SNIPPET_MAX_CHARS:
        body = body[:BODY_SNIPPET_MAX_CHARS].rstrip() + "…"

    title = f"First Response SLA {threshold_label}: {subject}"
    who = f"{client_name} ({from_name})" if from_name else (client_name or "Unknown sender")
    message = f"From {who}: \"{subject}\" is still awaiting first response."
    if body:
        message += f"\n\n{body}"

    return title, message

# Shared by SLASweepService (both clock types) and
# SLAService.complete_first_response_clock (First Response only) —
# the sweep already had its own copy of this map; kept here so there's
# one definition instead of two that could drift apart.
NOTIFICATION_TYPE_BY_THRESHOLD = {
    "HALF_ELAPSED": NotificationType.SLA_HALF_ELAPSED,
    "AT_RISK": NotificationType.SLA_AT_RISK,
    "BREACHED": NotificationType.SLA_BREACHED,
    "ESCALATED": NotificationType.SLA_ESCALATED,
}

CLOCK_TYPE_FIRST_RESPONSE = "FIRST_RESPONSE"


async def resolve_global_inbox_user_ids(user_repository: UserRepository) -> set[UUID]:
    """
    Site Lead + Super Admin — the GLOBAL_INBOX recipient role never
    varies per-clock, so both callers (the sweep, once per run; the
    completion hook, once per completed clock that turns out to have
    breached) resolve it the same way rather than duplicating the
    role-name loop.
    """

    recipients: set[UUID] = set()
    for role_name in GLOBAL_INBOX_ROLE_NAMES:
        users = await user_repository.list_active_by_role_name(role_name)
        recipients.update(u.user_id for u in users)
    return recipients


async def send_notification_emails(
    *,
    recipient_ids: set[UUID],
    subject: str,
    body: str,
    user_repository: UserRepository,
) -> None:
    """
    Sends the same real outbound email to every resolved recipient —
    one shared "resolve emails, then dispatch" step used by both First
    Response and Resolution SLA breach notifications, instead of two
    copies. get_email_sender() itself falls back to logging-only until
    smtp_host is configured (see app/core/email_sender.py), and
    EmailSender.send already swallows/logs its own failures, so a bad
    address or transport outage here can never block the SLA
    bookkeeping or business action that triggered it.
    """

    if not recipient_ids:
        return

    emails_by_id = await user_repository.get_emails_by_ids(list(recipient_ids))
    email_sender = get_email_sender()
    for email in emails_by_id.values():
        await email_sender.send(to_email=email, subject=subject, body=body)


def build_absolute_link(relative_path: str) -> str:
    base = get_settings().app_frontend_url
    if base:
        return f"{base.rstrip('/')}{relative_path}"
    # No frontend URL configured — still useful as plain text, just
    # not a clickable link inside the email client.
    return f"(open the app and go to {relative_path})"


async def notify_first_response_threshold(
    *,
    clock: FirstResponseSLA,
    threshold: str,
    client: Client | None,
    global_inbox_ids: set[UUID],
    notification_service: NotificationService | None,
    user_repository: UserRepository | None = None,
    interaction: Interaction | None = None,
) -> bool:
    """
    Resolves FIRST_RESPONSE_RULES' recipients for one already-confirmed
    -newly-crossed threshold (the idempotency check — try_record_many
    against SLABreachNotification — must have already happened by the
    time this is called; there is no idempotency check in here) and
    notifies them, in-app and (if `user_repository` is given) by real
    email too. Returns whether the in-app notification was sent (email
    delivery doesn't affect this return value — it's a side effect,
    not this function's core contract, and every existing caller's
    `notifications_sent` counting already depends on this meaning
    exactly "in-app notification created").

    `interaction` is passed in already-loaded (batch-prefetched by the
    sweep, or a single fetch at the one-off completion-time call site)
    rather than fetched in here, matching `client`'s own existing
    convention — this function only ever composes/sends, never queries.
    """

    ctx = RecipientContext(client=client, global_inbox_ids=global_inbox_ids)
    recipient_ids = resolve_recipients(FIRST_RESPONSE_RULES, threshold, ctx)

    if not recipient_ids:
        return False

    title, message = _first_response_notification_copy(
        interaction=interaction, client=client, threshold=threshold
    )

    # Points at the specific pending email, not just the bare inbox —
    # InboxPage.tsx reads this interaction_id on load and opens that
    # exact message instead of leaving the recipient to hunt for it.
    inbox_link = f"/inbox?interaction_id={clock.interaction_id}"

    sent = False
    if notification_service is not None:
        await notification_service.notify(
            recipient_ids,
            NOTIFICATION_TYPE_BY_THRESHOLD[threshold],
            title=title,
            message=message,
            link=inbox_link,
            related_entity_type="interaction",
            related_entity_id=clock.interaction_id,
        )
        sent = True

    if user_repository is not None:
        await send_notification_emails(
            recipient_ids=recipient_ids,
            subject=title,
            body=f"{message}\n\nView it here: {build_absolute_link(inbox_link)}",
            user_repository=user_repository,
        )

    return sent

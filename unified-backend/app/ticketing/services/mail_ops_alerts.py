# mail_ops_alerts.py
#
# Phase 2 hardening: operational-visibility notifications for the
# Graph-only background inbound transports (poller, webhook) — kept in
# its own module (rather than importing between graph_mail_poller.py
# and app/ticketing/api/mail_integration.py directly) so neither one
# needs to import the other.

from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService, NotificationType
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.sla_breach_notifier import resolve_global_inbox_user_ids

# How much of the subject to fold into the notification body.
_SUBJECT_SNIPPET_MAX_CHARS = 200


async def notify_unmatched_inbox_email(
    db: AsyncSession,
    *,
    from_email: str | None,
    subject: str | None,
    mailbox_address: str,
) -> None:
    """
    EmailService.receive_email already refused to persist this message
    ("Unknown inbox address.") — this is purely an ops-visibility
    notification about that refusal, reusing the same Site Lead/Super
    Admin audience resolve_global_inbox_user_ids already established
    elsewhere (the identical audience EmailService's own shared-
    mailbox fallback notifies). Deliberately NEVER creates a Client,
    Category, or Interaction row — see the two call sites
    (graph_mail_poller.py, mail_integration.py) for why this is safe
    to call after their own db.rollback().
    """

    recipient_ids = await resolve_global_inbox_user_ids(UserRepository(db))

    subject_snippet = (subject or "(no subject)")[:_SUBJECT_SNIPPET_MAX_CHARS]

    await NotificationService(NotificationRepository(db)).notify(
        recipient_ids,
        NotificationType.UNMATCHED_INBOX_EMAIL,
        title=f"Unmatched inbox address: {mailbox_address}",
        message=f"From {from_email or '(unknown sender)'}: {subject_snippet}",
    )
    await db.commit()


async def notify_mailbox_poll_stalled(
    db: AsyncSession,
    *,
    mailbox_address: str,
    consecutive_failures: int,
    error_summary: str,
) -> None:
    """
    A polled mailbox has failed to fetch messages for
    Settings.graph_mail_poll_stall_alert_minutes straight — most
    commonly a Graph 403/404 on that specific mailbox
    (graph_mail_poller.py's GraphAPIError branch). Unlike
    notify_unmatched_inbox_email above, no message was ever even
    listed here, so this never touches inbound_mail_failures either —
    same Site Lead/Super Admin audience, same "purely a notification,
    creates no Client/Category/Interaction row" shape.
    """

    recipient_ids = await resolve_global_inbox_user_ids(UserRepository(db))

    await NotificationService(NotificationRepository(db)).notify(
        recipient_ids,
        NotificationType.MAILBOX_POLL_STALLED,
        title=f"Mail polling stalled: {mailbox_address}",
        message=(
            f"Failed {consecutive_failures} consecutive poll ticks: "
            f"{error_summary[:_SUBJECT_SNIPPET_MAX_CHARS]}"
        ),
    )
    await db.commit()

# email_notifier.py

import asyncio
import logging
from typing import TYPE_CHECKING

from app.core.email_sender import get_email_sender
from app.notifications.email_content import build_notification_email, load_ticket_context
from app.notifications.email_policy import is_email_eligible

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.notifications.models import Notification
    from app.ticketing.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

# asyncio.create_task's returned Task is only weakly reachable via the
# event loop's own internals — with no strong reference held anywhere,
# it can be garbage-collected mid-flight. This module-level set is
# that reference (the pattern asyncio's own docs recommend for
# fire-and-forget tasks); each task removes itself once done.
_background_tasks: set[asyncio.Task] = set()


async def dispatch_notification_emails(
    created: list["Notification"],
    *,
    db: "AsyncSession",
    user_repository: "UserRepository",
) -> None:
    """
    The real send loop for one notify() call's freshly-created rows —
    kept separate from queue_notification_emails (the fire-and-forget
    wrapper below) so tests can await it directly and deterministically
    instead of racing a background task. Never raises: every
    per-recipient failure is caught, logged, and skipped, so one bad
    address or a transport outage can never take down the rest of the
    batch or propagate anywhere the triggering request could see it.
    """

    eligible = [n for n in created if is_email_eligible(n.notification_type)]
    if not eligible:
        return

    recipient_ids = {n.user_id for n in eligible}
    emails_by_user_id = await user_repository.get_active_emails_by_ids(list(recipient_ids))

    email_sender = get_email_sender()

    for notification in eligible:
        to_email = emails_by_user_id.get(notification.user_id)
        if not to_email:
            # Deactivated, or the user row is gone — either way, per
            # the recipient rules, skip rather than email a stale
            # address or no one at all.
            logger.info(
                "EMAIL_SKIPPED notification_id=%s notification_type=%s "
                "recipient_user_id=%s reason=no_active_email",
                notification.notification_id,
                notification.notification_type,
                notification.user_id,
            )
            continue

        try:
            ticket_context = await load_ticket_context(
                db,
                related_entity_type=notification.related_entity_type,
                related_entity_id=notification.related_entity_id,
            )
            subject, text_body, html_body = build_notification_email(
                notification, ticket_context
            )
            sent = await email_sender.send(
                to_email=to_email, subject=subject, body=text_body, html_body=html_body
            )
        except Exception as exc:
            logger.warning(
                "EMAIL_FAILED notification_id=%s notification_type=%s "
                "recipient_email=%s subject=%r failure_reason=%s",
                notification.notification_id,
                notification.notification_type,
                to_email,
                notification.title,
                exc,
                exc_info=True,
            )
            continue

        logger.info(
            "EMAIL_%s notification_id=%s notification_type=%s recipient_email=%s subject=%r",
            "SENT" if sent else "FAILED",
            notification.notification_id,
            notification.notification_type,
            to_email,
            notification.title,
        )


def queue_notification_emails(created: list["Notification"]) -> None:
    """
    The fire-and-forget entry point NotificationService.notify() calls.
    Schedules dispatch_notification_emails on its own freshly-opened DB
    session (AsyncSessionLocal — the same factory app/core/
    sla_scheduler.py already uses for background work with no request
    context) rather than the caller's request-scoped session, since
    that session closes (its Depends(get_db) cleanup runs once the
    response finishes) on a timeline this background task doesn't
    share. This is what makes email delivery genuinely non-blocking:
    notify() returns immediately, and the caller's request is never
    held open waiting on SMTP.
    """

    if not any(is_email_eligible(n.notification_type) for n in created):
        return

    task = asyncio.create_task(_dispatch_with_own_session(created))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _dispatch_with_own_session(created: list["Notification"]) -> None:
    from app.database.session import AsyncSessionLocal
    from app.ticketing.repositories.user_repository import UserRepository

    try:
        async with AsyncSessionLocal() as db:
            await dispatch_notification_emails(created, db=db, user_repository=UserRepository(db))
    except Exception:
        # Belt-and-suspenders on top of dispatch_notification_emails'
        # own per-recipient try/except: a failure resolving the
        # recipient set itself (e.g. a DB connectivity blip) must also
        # never go anywhere — there is no caller left to propagate to
        # by the time this background task runs.
        logger.exception("EMAIL_DISPATCH_TASK_FAILED")

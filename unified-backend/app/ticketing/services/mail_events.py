# mail_events.py
#
# Real-time "new mail" signals for the Mail UI.
#
# Flow: EmailService.receive_email stores the new interaction and calls
# queue_mail_event(); the event is only PUBLISHED once the surrounding
# database transaction actually COMMITS (SQLAlchemy `after_commit`), and is
# silently discarded if it rolls back. So a browser is never told about mail
# the database doesn't have yet (it would refetch and not see it), and a
# failed/rolled-back ingestion never produces a phantom event.
#
# The event is an invalidation SIGNAL, not data: ids and a timestamp only —
# no sender, subject, body or addresses (PHI never rides the real-time
# channel). The browser reacts by refetching through the normal, RBAC-checked
# Inbox API. It travels over the existing per-user SSE stream
# (/notifications/stream, see notifications/sse_manager.py) as the `mail`
# event, delivered only to connections whose user can see the mail:
#
# - Site Lead / Super Admin (see everything): every mail event;
# - everyone else: only events that name their user id in the audience
#   EmailService computes — the same people MAIL_RECEIVED / CLIENT_REPLY
#   notify (the client's Account Manager or the category's Reporting
#   Managers, or the ticket's assigned agent + Team Lead).
#
# Under-delivery is harmless (Refresh and every normal navigation still
# fetch the truth); over-delivery would leak the existence of mail, so the
# audience is deliberately conservative.

import logging
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.notifications.sse_manager import get_notification_stream_manager

logger = logging.getLogger(__name__)

_PENDING_KEY = "utms_pending_mail_events"

MAIL_CREATED = "mail.created"
MAIL_UPDATED = "mail.updated"


def build_mail_event(
    *,
    interaction_id: UUID,
    parent_interaction_id: UUID | None,
    ticket_id: UUID | None,
) -> dict[str, Any]:
    """
    `mail.created` for a brand-new thread root, `mail.updated` for a
    message that landed on an existing thread. Ids and a timestamp only.
    """

    return {
        "type": MAIL_CREATED if parent_interaction_id is None else MAIL_UPDATED,
        "interaction_id": str(interaction_id),
        "thread_id": str(parent_interaction_id or interaction_id),
        "ticket_id": str(ticket_id) if ticket_id else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def queue_mail_event(
    db: Any, payload: dict[str, Any], audience_user_ids: Iterable[Any]
) -> None:
    """
    Remember an event to publish when `db`'s transaction commits. Never
    raises (a missing/odd session simply means no live event; ingestion is
    never affected).
    """

    try:
        info = db.sync_session.info
    except AttributeError:
        return

    audience = {str(user_id) for user_id in audience_user_ids if user_id}
    info.setdefault(_PENDING_KEY, []).append((payload, audience))


@event.listens_for(Session, "after_commit")
def _publish_after_commit(session: Session) -> None:
    pending = session.info.pop(_PENDING_KEY, None)
    if not pending:
        return

    manager = get_notification_stream_manager()
    for payload, audience in pending:
        try:
            manager.publish_mail_event(audience, payload)
        except Exception:  # noqa: BLE001 — a signal must never break a commit
            logger.warning("mail event publish failed", exc_info=True)


@event.listens_for(Session, "after_rollback")
def _discard_on_rollback(session: Session) -> None:
    # A rolled-back transaction's mail never existed: drop its events.
    session.info.pop(_PENDING_KEY, None)

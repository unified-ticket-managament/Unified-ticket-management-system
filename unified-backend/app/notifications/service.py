import logging
from uuid import UUID

from app.notifications.repository import NotificationRepository
from app.notifications.schemas import NotificationResponse
from app.notifications.sse_manager import get_notification_stream_manager

logger = logging.getLogger(__name__)


class NotificationType:
    """
    Plain string constants, not a Python/Postgres enum — see
    Notification.notification_type's own docstring for why.
    """

    MAIL_RECEIVED = "MAIL_RECEIVED"
    CLIENT_REPLY = "CLIENT_REPLY"
    TICKET_ASSIGNED = "TICKET_ASSIGNED"
    PERMISSION_REQUESTED = "PERMISSION_REQUESTED"
    PERMISSION_APPROVED = "PERMISSION_APPROVED"
    PERMISSION_REJECTED = "PERMISSION_REJECTED"
    PERMISSION_REVOKED = "PERMISSION_REVOKED"
    # A permission override granted directly (e.g. via the Users >
    # Permission Overrides admin screen) rather than through an
    # approved Permission Request — kept distinct from
    # PERMISSION_APPROVED so a recipient can tell "an admin proactively
    # gave me this" apart from "my own request was approved". See
    # PermissionOverrideService.grant's own `notify` parameter for why
    # this never fires alongside PERMISSION_APPROVED for the same
    # grant.
    PERMISSION_GRANTED = "PERMISSION_GRANTED"
    EDIT_ACCESS_REQUESTED = "EDIT_ACCESS_REQUESTED"
    EDIT_ACCESS_APPROVED = "EDIT_ACCESS_APPROVED"
    EDIT_ACCESS_REJECTED = "EDIT_ACCESS_REJECTED"
    SLA_HALF_ELAPSED = "SLA_HALF_ELAPSED"
    SLA_AT_RISK = "SLA_AT_RISK"
    SLA_BREACHED = "SLA_BREACHED"
    SLA_ESCALATED = "SLA_ESCALATED"
    ESCALATION_CREATED = "ESCALATION_CREATED"
    ESCALATION_ACKNOWLEDGED = "ESCALATION_ACKNOWLEDGED"
    ESCALATION_ADVANCED = "ESCALATION_ADVANCED"
    ESCALATION_CLOSED = "ESCALATION_CLOSED"
    TICKET_STATUS_CHANGED = "TICKET_STATUS_CHANGED"
    TICKET_PRIORITY_CHANGED = "TICKET_PRIORITY_CHANGED"
    TICKET_RESOLVED = "TICKET_RESOLVED"
    INTERNAL_NOTE_ADDED = "INTERNAL_NOTE_ADDED"


class NotificationService:
    """
    Single write path every trigger (mail intake, ticket assignment,
    permission requests, edit access) calls through — every business
    service that needs to notify someone holds one of these as an
    optional constructor dependency (`notification_service:
    NotificationService | None = None`, same optionality convention as
    e.g. InteractionService's `edit_access_repository`) so existing
    call sites that don't pass one keep working unchanged.
    """

    def __init__(self, notification_repository: NotificationRepository):
        self.notification_repository = notification_repository

    async def notify(
        self,
        user_ids,
        notification_type: str,
        title: str,
        message: str,
        *,
        link: str | None = None,
        related_entity_type: str | None = None,
        related_entity_id: UUID | None = None,
    ) -> None:
        """
        Fans one notification out to every id in `user_ids` (a list,
        set, or single UUID — normalized here so call sites don't each
        have to remember to dedupe/wrap). Silently no-ops on an empty
        recipient set rather than requiring every call site to check.
        """

        if isinstance(user_ids, UUID):
            user_ids = [user_ids]

        unique_ids = {uid for uid in user_ids if uid is not None}

        if not unique_ids:
            return

        rows = [
            {
                "user_id": uid,
                "notification_type": notification_type,
                "title": title,
                "message": message,
                "link": link,
                "related_entity_type": related_entity_type,
                "related_entity_id": related_entity_id,
            }
            for uid in unique_ids
        ]

        created = await self.notification_repository.create_many(rows)
        await self._publish_to_streams(created)

    async def _publish_to_streams(self, created: list) -> None:
        """
        Pushes each freshly-created row to any open SSE connection(s)
        for its own recipient (see app/notifications/sse_manager.py) —
        the real-time counterpart to this being visible via the next
        GET /notifications poll. Deliberately best-effort: skipped
        entirely for a recipient with no open connection (has_subscribers
        is a cheap in-memory check, avoiding the extra unread-count
        query for the common case), and never raises — a stream-publish
        failure must never fail the write path that created the
        notification in the first place.
        """

        manager = get_notification_stream_manager()

        for notification in created:
            user_id_str = str(notification.user_id)
            if not manager.has_subscribers(user_id_str):
                continue

            try:
                unread_count = await self.notification_repository.count_for_user(
                    notification.user_id, unread_only=True
                )
                payload = {
                    "notification": NotificationResponse.model_validate(
                        notification
                    ).model_dump(mode="json"),
                    "unread_count": unread_count,
                }
                await manager.publish(user_id_str, payload)
            except Exception:
                # Never let a stream-publish problem surface as a
                # failure of the action that triggered the notification
                # (a ticket transfer, an SLA breach, ...) — the row is
                # already durably created; the caller's next ordinary
                # GET /notifications poll/refresh still picks it up.
                logger.warning(
                    "SSE_PUBLISH_FAILED user_id=%s notification_id=%s",
                    user_id_str,
                    notification.notification_id,
                    exc_info=True,
                )
                continue

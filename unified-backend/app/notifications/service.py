from uuid import UUID

from app.notifications.repository import NotificationRepository


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
    EDIT_ACCESS_REQUESTED = "EDIT_ACCESS_REQUESTED"
    EDIT_ACCESS_APPROVED = "EDIT_ACCESS_APPROVED"
    EDIT_ACCESS_REJECTED = "EDIT_ACCESS_REJECTED"


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

        await self.notification_repository.create_many(rows)

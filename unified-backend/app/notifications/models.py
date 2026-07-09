import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


class Notification(Base):
    """
    A single in-app notification for one recipient. `notification_type`
    is a plain string (not a native Postgres enum) — same reasoning as
    `Interaction.interaction_type`/`PermissionRequest.status`: this set
    is expected to keep growing, and a free-form column needs no
    enum-widening migration to add a new type.

    Cross-cutting by design: written from both RBAC-flavored triggers
    (permission requests) and Ticketing-flavored triggers (mail,
    tickets, edit access) now that both live in one unified backend —
    see app/notifications/service.py for the single write path both
    sides call through.
    """

    __tablename__ = "notifications"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
        index=True,
    )

    notification_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Where clicking the notification should navigate to — a frontend
    # route path (e.g. "/tickets/{id}"), not a full URL. Nullable since
    # not every notification has an obvious destination.
    link: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # Loosely-typed reference back to whatever this notification is
    # about (a ticket, an interaction, a permission request, an edit
    # access request) — free-form like Interaction.interaction_type,
    # not an FK, since it can point at rows in different tables.
    related_entity_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    is_read: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

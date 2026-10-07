import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


class MailReminderStatus:
    """
    String constants, not a DB enum — same convention as
    NotificationType and Interaction.dispatch_status, so adding a
    status never needs an enum-widening migration.
    """

    ACTIVE = "ACTIVE"
    FIRED = "FIRED"
    DISMISSED = "DISMISSED"
    CANCELED = "CANCELED"

    ALL = (ACTIVE, FIRED, DISMISSED, CANCELED)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MailReminder(Base):
    """
    A user's personal "Remind me" on a mail thread — like
    MessageMark / MessageReadReceipt, one user's reminder is never
    visible to another, and it is keyed by the thread ROOT interaction
    so a reply's id maps onto the same row the list view reads.

    `remind_at` is always a UTC instant (timestamptz); display timezone
    is a client concern. Snoozing reuses the same row (remind_at moves,
    status returns to ACTIVE, snooze_count increments).

    At most one ACTIVE reminder per (user, thread) — enforced by a
    partial unique index so history rows (FIRED / DISMISSED / CANCELED)
    can coexist with a fresh ACTIVE one.
    """

    __tablename__ = "mail_reminders"

    reminder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )

    interaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interactions.interaction_id", ondelete="CASCADE"),
        nullable=False,
    )

    remind_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MailReminderStatus.ACTIVE
    )

    snooze_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index(
            "uq_mail_reminders_active_user_interaction",
            "user_id",
            "interaction_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index(
            "idx_mail_reminders_active_remind_at",
            "remind_at",
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("idx_mail_reminders_user_status", "user_id", "status"),
    )

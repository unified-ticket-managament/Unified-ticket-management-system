import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


class MessageReadReceipt(Base):
    """
    Records that a given user has opened a given inbox thread root —
    the persisted counterpart to what was previously only a client-
    side, session-only `openedIds` Set (reset on every page reload,
    never shared across devices/sessions/agents). Purely additive: the
    Mail UI's existing unread behavior is unchanged unless/until the
    frontend is wired to read `InboxItemResponse.is_read` instead of
    (or alongside) its own local state — see that field's docstring.

    One row per (user, interaction) — written once per thread-open via
    an idempotent upsert (`ON CONFLICT DO NOTHING`); never updated or
    deleted, so `read_at` is always the *first* time this user opened
    this thread.
    """

    __tablename__ = "message_read_receipts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        primary_key=True,
    )

    interaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interactions.interaction_id"),
        primary_key=True,
    )

    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


class MessageMark(Base):
    """
    A user's own Flag / Pin on a mail thread root — personal, like
    MessageReadReceipt (one user's flag or pin is never visible to
    another). Keyed by the thread root so a reply's id maps onto the
    same row the list view reads.

    One row per (user, interaction); `flagged_at` / `pinned_at` are NULL
    when that mark is off. A row with both NULL is deleted, so the table
    only holds live marks.
    """

    __tablename__ = "message_marks"

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

    flagged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

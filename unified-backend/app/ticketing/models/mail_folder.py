import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


class MailFolder(Base):
    """
    A custom folder agents can file a mail item into — e.g. "Billing",
    "Claims", "General". Global/shared across the org, not per-user
    (matches how these are presented — a plain, unscoped list, not
    "my folders" vs. someone else's). Orthogonal to the
    pending/replied/ticketed/archived status pipeline: an item can be
    "Ticketed" AND filed under "Billing" at the same time — folder
    assignment (`Interaction.folder_id`) never changes `status`.
    """

    __tablename__ = "mail_folders"

    folder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

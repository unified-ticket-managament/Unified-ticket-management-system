import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean
from sqlalchemy import Enum as SQLEnum
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
#interaction.py
from app.enums import (
    InteractionDirection,
    InteractionStatus,
)
from shared_models.database import Base

if TYPE_CHECKING:
    from shared_models.models import User
    from .attachment import Attachment
    from .ticket import Ticket


class Interaction(Base):
    """
    Interaction Model
    """

    __tablename__ = "interactions"

    interaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.ticket_id"),
        nullable=True,
    )

    interaction_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    status: Mapped[InteractionStatus] = mapped_column(
        SQLEnum(
            InteractionStatus,
            name="interaction_status_enum",
        ),
        default=InteractionStatus.PENDING,
        nullable=False,
    )

    direction: Mapped[InteractionDirection] = mapped_column(
        SQLEnum(
            InteractionDirection,
            name="interaction_direction_enum",
        ),
        nullable=False,
    )

    performed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    payload: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    is_visible: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    removed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    removed_at:Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    message_id: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    default=lambda: datetime.now(timezone.utc),
    nullable=False,
    )

    # ------------------------

    ticket: Mapped["Ticket"] = relationship(
        "Ticket",
        back_populates="interactions",
    )

    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment",
        back_populates="interaction",
        cascade="all, delete-orphan",
    )
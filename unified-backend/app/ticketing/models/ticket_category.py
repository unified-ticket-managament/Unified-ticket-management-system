import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

#ticket_category.py
class TicketCategory(Base):
    """
    One category a ticket belongs to — the source of truth for
    multi-category tickets. Categories are work scope / visibility
    only: they never own an SLA clock and never create a user
    assignment on their own.

    Legacy projection: Ticket.ticket_type (a category NAME string)
    mirrors the PRIMARY row's category name, kept in sync by
    TicketAssignmentService — every existing single-category reader
    keeps working unchanged.

    FK by category_id (not name), so a later category rename can't
    orphan these rows the way it can orphan Ticket.ticket_type.
    Removal is a hard delete; the CATEGORY_REMOVED audit event is the
    history.
    """

    __tablename__ = "ticket_categories"

    ticket_category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.ticket_id"),
        nullable=False,
        index=True,
    )

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.category_id"),
        nullable=False,
        index=True,
    )

    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("ticket_id", "category_id", name="uq_ticket_categories_ticket_category"),
        Index(
            "uq_ticket_categories_one_primary",
            "ticket_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

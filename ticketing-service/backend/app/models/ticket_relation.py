import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


class TicketRelation(Base):
    """
    A "Related Tickets" link between two tickets — symmetric, so one
    logical relationship is stored as two rows (ticket_id/related_
    ticket_id and its mirror), written together at creation. That
    trades write amplification for a read side that's always a single
    `WHERE ticket_id = :id` query, no OR-across-two-columns query
    needed to find a ticket's related tickets regardless of which
    side of the pair it was linked from.
    """

    __tablename__ = "ticket_relations"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.ticket_id"),
        primary_key=True,
    )

    related_ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.ticket_id"),
        primary_key=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

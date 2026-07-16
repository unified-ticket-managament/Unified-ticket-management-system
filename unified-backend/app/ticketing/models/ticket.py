import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

#ticket.py
from app.ticketing.enums import TicketPriority, TicketStatus
from shared_models.database import Base

if TYPE_CHECKING:
    from shared_models.models import User
    from .interaction import Interaction


class Ticket(Base):
    """
    Ticket Model
    """

    __tablename__ = "tickets"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Legacy FK to an individual `users` row — kept nullable only so
    # existing rows created before the client-company model stay
    # valid. New tickets leave this NULL and use client_company_id
    # instead; do not write to this column going forward.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    # The client (company) this ticket belongs to. Ownership is the
    # company's Account Manager (clients.account_manager_id), not
    # this ticket's agent_id — agent_id is only "who is currently
    # working on it" (set via claim/transfer).
    client_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.client_id"),
        nullable=True,
        index=True,
    )

    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
        index=True,
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    ticket_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    current_status: Mapped[TicketStatus] = mapped_column(
        SQLEnum(
            TicketStatus,
            name="ticket_status_enum",
        ),
        default=TicketStatus.OPEN,
        nullable=False,
        index=True,
    )

    current_priority: Mapped[TicketPriority] = mapped_column(
        SQLEnum(
            TicketPriority,
            name="ticket_priority_enum",
        ),
        default=TicketPriority.MEDIUM,
        nullable=False,
    )

    custom_fields: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Who closed the ticket (Close Ticket action) — cleared back to
    # None on reopen, same lifecycle as closed_at.
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ------------------------

    interactions: Mapped[list["Interaction"]] = relationship(
        "Interaction",
        back_populates="ticket",
    )
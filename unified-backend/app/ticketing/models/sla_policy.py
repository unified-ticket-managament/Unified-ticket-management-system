import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

from app.ticketing.enums import TicketPriority

#sla_policy.py
class SLAPolicy(Base):
    """
    One row per TicketPriority — the target minutes both SLA clocks
    (First Response, Resolution) are measured against. Global across
    every client/category for v1; a client- or category-specific
    override isn't modeled here (see the plan doc's locked decision to
    key policy by priority alone).

    Seeded at migration time (three rows, one per TicketPriority
    member) — never created/deleted independently, since the set of
    priorities itself already needs its own migration to change.
    """

    __tablename__ = "sla_policies"

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    priority: Mapped[TicketPriority] = mapped_column(
        SQLEnum(
            TicketPriority,
            name="ticket_priority_enum",
        ),
        unique=True,
        nullable=False,
    )

    first_response_target_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    resolution_target_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
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

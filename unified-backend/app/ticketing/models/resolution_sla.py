import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

from app.ticketing.enums import SLAClockStatus, TicketPriority

#resolution_sla.py
class ResolutionSLA(Base):
    """
    Resolution SLA clock — 1:1 with a Ticket. Starts when the ticket
    is created (or resumes when a customer reply lands on an existing
    ticket whose clock had paused), pauses while waiting on the
    customer, and completes only when a supervisor closes the ticket
    (see InteractionService.change_status's CLOSED-transition gate —
    entering RESOLVED never completes this clock).

    `due_at` is a single mutable timestamp shifted forward by the
    exact pause duration on every resume, NOT an accumulated-elapsed-
    time computation — this keeps the periodic breach sweep a cheap,
    indexed `WHERE status = 'RUNNING' AND due_at < now()` query. See
    the plan doc's §0 for the full justification.
    """

    __tablename__ = "resolution_slas"

    resolution_sla_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.ticket_id"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Denormalized off Ticket.client_company_id, same rationale as
    # FirstResponseSLA.client_id — saves a join during the sweep.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.client_id"),
        nullable=True,
        index=True,
    )

    # Snapshotted at ticket-creation time. Reshifted (not left stale)
    # if the ticket's priority changes mid-flight — see
    # InteractionService.change_priority's due_at recompute.
    priority: Mapped[TicketPriority] = mapped_column(
        SQLEnum(
            TicketPriority,
            name="ticket_priority_enum",
        ),
        nullable=False,
    )

    status: Mapped[SLAClockStatus] = mapped_column(
        SQLEnum(
            SLAClockStatus,
            name="sla_clock_status_enum",
        ),
        default=SLAClockStatus.RUNNING,
        nullable=False,
        index=True,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # Non-null iff status == PAUSED; cleared back to None on resume.
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Running total, display-only — NOT read by the sweep or by the
    # due_at shift math (that's computed inline at pause/resume time).
    # Exists purely so "how long has this ticket cumulatively waited
    # on the customer" can be shown without summing the pause-interval
    # audit table on every read.
    total_paused_seconds: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    __table_args__ = (
        # The breach sweep's primary query path:
        # WHERE status = 'RUNNING' AND due_at < :now — paused clocks
        # are naturally excluded by the status filter, no extra logic
        # needed.
        Index("ix_resolution_slas_status_due_at", "status", "due_at"),
    )

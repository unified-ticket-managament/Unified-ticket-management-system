import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

from app.ticketing.enums import SLAClockStatus, TicketPriority

#ticket_assignment_sla.py
class TicketAssignmentSLA(Base):
    """
    One Resolution SLA *run* for one TicketAssignment — every
    explicitly assigned user gets their own independent clock. Never
    created for a category.

    Same clock semantics as the ticket-level ResolutionSLA (and the
    same pause/resume due_at-shift math — see
    ResolutionSLARepository): RUNNING -> PAUSED (WAITING_FOR_CLIENT)
    -> RUNNING ... -> COMPLETED. Unlike ResolutionSLA, which reopens
    in place, a reopen here starts a NEW row (run_number + 1) so every
    earlier run's breach/completion stays as permanent history.

    The ticket-level ResolutionSLA is untouched by this table and
    keeps driving escalation, list SLA tiers and dashboards exactly as
    before (it is the primary's accountability clock).

    At most one live (not COMPLETED) run per assignment — enforced by
    a partial unique index, so a duplicate timer can't be created by a
    re-assign, a primary change, a close or a reopen racing another
    request.
    """

    __tablename__ = "ticket_assignment_slas"

    assignment_sla_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ticket_assignments.assignment_id"),
        nullable=False,
        index=True,
    )

    # Denormalized off the assignment for the sweep/reporting (avoids a
    # join back through ticket_assignments on every tick).
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.ticket_id"),
        nullable=False,
        index=True,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )

    run_number: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    priority: Mapped[TicketPriority] = mapped_column(
        SQLEnum(TicketPriority, name="ticket_priority_enum", create_type=False),
        nullable=False,
    )

    status: Mapped[SLAClockStatus] = mapped_column(
        SQLEnum(SLAClockStatus, name="sla_clock_status_enum", create_type=False),
        default=SLAClockStatus.RUNNING,
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    active_target_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    total_paused_seconds: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # RESOLVED / TICKET_CLOSED / UNASSIGNED / STATUS_CHANGED — free
    # string, same convention as FirstResponseSLA.completion_reason.
    completion_reason: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    # Stamped once, the first time the sweep sees due_at < now() on a
    # RUNNING run — never cleared, kept as history after completion.
    breached_at: Mapped[datetime | None] = mapped_column(
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
        UniqueConstraint("assignment_id", "run_number", name="uq_ticket_assignment_slas_run"),
        Index(
            "uq_ticket_assignment_slas_one_live_run",
            "assignment_id",
            unique=True,
            postgresql_where=text("status <> 'COMPLETED'"),
        ),
        # Sweep path: WHERE status = 'RUNNING' AND due_at < :now.
        Index("ix_ticket_assignment_slas_status_due_at", "status", "due_at"),
    )

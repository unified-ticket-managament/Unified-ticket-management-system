import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

from app.ticketing.enums import SLAClockStatus

#escalation_handling_sla.py
class EscalationHandlingSLA(Base):
    """
    A second, internal-only clock — completely separate from (and never
    touches) ResolutionSLA — that starts the moment a TicketEscalation
    is first acknowledged (or an assignment to staff is treated as
    acknowledgment, see EscalationService.acknowledge_via_assignment).
    Its target is a fixed fraction of the ORIGINAL Resolution SLA's
    configured target duration (see escalation_handling_sla_service.
    compute_escalation_handling_target_seconds — 25% today, but this
    table stores the resolved `target_seconds` rather than
    re-deriving it from a policy row at read time, so a later policy
    edit never retroactively changes an already-started clock's due
    date, matching ResolutionSLA's own established convention).

    1:1 with a TicketEscalation (one row per escalation instance, not
    per ticket — closing an escalation and later re-escalating the
    same ticket gets a fresh escalation_id and thus a fresh row here
    too). `ticket_id` is denormalized off the escalation for the
    sweep's own query convenience (avoids a join back through
    ticket_escalations just to filter/report by ticket).

    Deliberately reuses SLAClockStatus (RUNNING/COMPLETED only, never
    PENDING/PAUSED for this table) rather than inventing a fourth
    clock-status enum — see the Postgres-enum migration gotcha in
    CLAUDE.md if a status value here ever needs to change.
    """

    __tablename__ = "escalation_handling_slas"

    escalation_handling_sla_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    escalation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ticket_escalations.escalation_id"),
        unique=True,
        nullable=False,
        index=True,
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.ticket_id"),
        nullable=False,
        index=True,
    )

    status: Mapped[SLAClockStatus] = mapped_column(
        SQLEnum(SLAClockStatus, name="sla_clock_status_enum", create_type=False),
        default=SLAClockStatus.RUNNING,
        nullable=False,
        index=True,
    )

    # The resolved 25%-of-original-target duration, in seconds — see
    # this model's own docstring for why it's stored, not re-derived.
    target_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    # Stamped exactly once, the first time the sweep observes
    # due_at < now() — never cleared, never re-stamped, so this also
    # doubles as the sweep's own idempotency guard for "have we
    # already advanced the escalation for this breach" (see
    # EscalationHandlingSlaRepository.list_newly_breached).
    breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    __table_args__ = (
        # The sweep's breach-detection query path:
        # WHERE status = 'RUNNING' AND breached_at IS NULL AND due_at < :now.
        Index(
            "ix_escalation_handling_slas_status_due_at",
            "status",
            "due_at",
        ),
    )

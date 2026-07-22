import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

#sla_breach_notification.py
class SLABreachNotification(Base):
    """
    Idempotency ledger for the breach sweep — the load-bearing table
    for sweep correctness. `clock_id` is polymorphic (points at either
    a FirstResponseSLA or a ResolutionSLA row depending on
    `clock_type`) with no DB-level FK constraint, since Postgres can't
    express "FK into one of two tables" — same trade-off AuditLog's
    own `entity_id` already makes in this codebase. Enforced only in
    application code (SLASweepService), never written to directly by
    anything else.

    The sweep does `INSERT ... ON CONFLICT (clock_type, clock_id,
    threshold, cycle) DO NOTHING` and only fires a notification when the
    insert actually happens (checked via RETURNING) — safe even
    against two overlapping sweep runs, with no application-level
    lock needed. `cycle` was added alongside the original three columns
    (see its own docstring below) after a real bug: without it, a
    Resolution clock's HALF_ELAPSED/AT_RISK/BREACHED could only ever
    notify once in the clock's whole lifetime, even across a legitimate
    escalation-driven restart of the same clock row.
    """

    __tablename__ = "sla_breach_notifications"

    sla_breach_notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # FIRST_RESPONSE or RESOLUTION — a free string (only two literal
    # values ever), avoiding a third native Postgres enum type for a
    # column no downstream query ever filters on independently of
    # clock_id.
    clock_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    clock_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )

    # AT_RISK (80%) / BREACHED (100%) / ESCALATED (150%).
    threshold: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    # Which restart of the underlying clock this notification belongs
    # to — always 0 for a First Response clock (never restarts) and
    # for a Resolution clock's pre-escalation life; bumped to match
    # ResolutionSLA.escalation_cycle every time
    # restart_due_at_for_escalation resets that same clock row's due_at
    # for a new handling stage. Without this, a threshold that already
    # fired once for a given clock_id could never fire again after a
    # legitimate restart, since the clock_id itself never changes — see
    # this table's own class docstring.
    cycle: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        # THE idempotency guarantee — one notification per
        # (clock, threshold, cycle) triple, ever. `cycle` is what lets
        # a legitimate clock restart (escalation handling-stage
        # acceptance) re-fire a threshold that already notified once in
        # an earlier cycle, without reopening the door to a genuine
        # duplicate within the same cycle.
        Index(
            "ix_sla_breach_notifications_unique",
            "clock_type",
            "clock_id",
            "threshold",
            "cycle",
            unique=True,
        ),
    )

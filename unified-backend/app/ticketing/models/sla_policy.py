import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
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

    # How long a TicketEscalation's current-level owner has to
    # acknowledge before the sweep auto-advances to the next level
    # (TEAM_LEAD -> MANAGER -> SITE_LEAD) — see ticket_escalation.py.
    # Kept on this same per-priority table rather than a new one, same
    # rationale as the two targets above.
    escalation_ack_target_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Superseded by handling_stage_percentages below (2026-07-20) — a
    # single flat fraction can't express a per-stage percentage, which
    # is the whole point of the handling-stage redesign. Left in place,
    # unread by current code, rather than dropped/renamed: per this
    # session's "migrate behavior first, verify nothing depends on it,
    # remove in a later cleanup phase" decision. Do not read this column
    # in new code — use handling_stage_percentages instead.
    handling_sla_percentage: Mapped[float] = mapped_column(
        Float,
        default=25.0,
        nullable=False,
    )

    # Ordered, configurable per-stage percentages of THIS priority's
    # resolution_target_minutes — index 0 is stage 1's percentage,
    # index 1 is stage 2's, etc. A stage beyond this list's length
    # repeats the last configured value (see
    # EscalationHandlingSlaService.resolve_stage_percentage) rather than
    # growing unboundedly. Stored as whole percentages (25.0, 12.5, ...),
    # same convention as the superseded handling_sla_percentage above.
    handling_stage_percentages: Mapped[list[float]] = mapped_column(
        JSONB,
        nullable=False,
    )

    # Per-priority overrides for the sweep's HALF_ELAPSED/AT_RISK
    # elapsed-fraction thresholds (see sla_escalation_rules.py's
    # thresholds_reached) — BREACHED (100%) and ESCALATED (150%) stay
    # fixed globally; only these two "warning" tiers are configurable
    # per priority, matching the admin-facing SLA Timing Matrix's
    # "Warning 1"/"Warning 2" columns. Whole percentages (50.0/80.0),
    # same convention as handling_sla_percentage above.
    warning_1_percentage: Mapped[float] = mapped_column(
        Float,
        default=50.0,
        nullable=False,
    )

    warning_2_percentage: Mapped[float] = mapped_column(
        Float,
        default=80.0,
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

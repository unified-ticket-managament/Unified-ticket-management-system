import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

from app.ticketing.enums import EscalationLevel, EscalationStatus, TicketPriority

#ticket_escalation.py
class TicketEscalation(Base):
    """
    Internal escalation ownership/acknowledgment tracker — separate
    from (and never mutates) ResolutionSLA. A ticket's Resolution SLA
    keeps its own started_at/due_at/breach state exactly as if no
    escalation had ever happened; this table only tracks *who currently
    owns following up* and *by when they must acknowledge*, advancing
    up the TEAM_LEAD -> MANAGER -> SITE_LEAD chain (EscalationLevel) if
    ignored. At most one non-CLOSED row exists per ticket at a time
    (enforced by a partial unique index — see the migration), but
    CLOSED rows are kept for history rather than deleted.

    `owner_ids` is a JSONB list of user_id strings rather than a join
    table: a level can resolve to more than one user (e.g. every Team
    Lead for a still-unclaimed ticket's category), and this list is
    wholesale-replaced on every advance/create — never queried by its
    contents, only displayed — so a join table would add a round trip
    for no real benefit over this codebase's existing JSONB usage
    (Ticket.custom_fields).
    """

    __tablename__ = "ticket_escalations"

    escalation_id: Mapped[uuid.UUID] = mapped_column(
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

    # Denormalized link to the ticket's own Resolution SLA — read-only
    # convenience for the frontend (show both side by side), never
    # written back to by this table.
    resolution_sla_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resolution_slas.resolution_sla_id"),
        nullable=True,
    )

    level: Mapped[EscalationLevel] = mapped_column(
        SQLEnum(EscalationLevel, name="ticket_escalation_level_enum"),
        nullable=False,
    )

    status: Mapped[EscalationStatus] = mapped_column(
        SQLEnum(EscalationStatus, name="ticket_escalation_status_enum"),
        default=EscalationStatus.ACTIVE,
        nullable=False,
        index=True,
    )

    # Every current owner's user_id, as strings — see class docstring.
    owner_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )

    # The ticket's priority as of THIS escalation's creation, captured
    # before EscalationService._set_ticket_priority_to_critical
    # overwrites Ticket.current_priority to CRITICAL — the only durable,
    # queryable record of what it used to be (otherwise recoverable only
    # from the audit log's PRIORITY_CHANGED old_values). Also the gate
    # for how long the Resolution SLA clock keeps running against its
    # original target rather than CRITICAL's — see
    # has_advanced_past_starting_level below.
    original_priority: Mapped[TicketPriority] = mapped_column(
        SQLEnum(TicketPriority, name="ticket_priority_enum"),
        nullable=False,
    )

    # False for the escalation's original starting level. Flips to True
    # the moment evaluate_overdue/advance_for_handling_sla_breach
    # actually advances the level past where it started — i.e. the
    # first owner didn't act in time. Purely an "has the ownership
    # ladder ever moved" fact now — kept for display/audit purposes,
    # but no longer used to decide whether to reshift the Resolution
    # SLA clock (see handling_stage below, which tracks the genuinely
    # different "how many real accept-assign-breach cycles have
    # occurred" fact instead). Ladder movement caused by an
    # acknowledgment-window timeout must never be conflated with a
    # genuine handling-stage breach — that conflation was the bug this
    # column's old reshift-gating role produced.
    has_advanced_past_starting_level: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
    )

    # ---------------------------------------------------------
    # Handling progression — independent of the ownership ladder
    # above. handling_stage is 0 until the first genuine acceptance
    # completes (EscalationService._complete_acceptance), and only
    # ever increments when a stage's own window elapses AND a new
    # acceptance completes at whatever level the ladder has since
    # reached — never on a bare ack-timeout ladder advance (evaluate_
    # overdue never touches these three fields).
    #
    # handling_stage_started_at/handling_stage_due_at describe the
    # CURRENT stage's window; both NULL whenever no stage is presently
    # running (before the first acceptance, or between a stage's
    # breach and the next acceptance). "Breached" is derived by
    # comparing handling_stage_due_at to now rather than a separate
    # boolean column — the sweep clears handling_stage_due_at back to
    # NULL once it has acted on a breach, which doubles as the
    # idempotency guard (a stage is "currently running" iff this field
    # is non-null).
    # ---------------------------------------------------------

    handling_stage: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
    )

    handling_stage_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    handling_stage_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # MANUAL (an agent/supervisor used ticket:escalate) or
    # AUTO_SLA_BREACH (the sweep created it the moment Resolution SLA
    # first crossed ESCALATED, 150% elapsed, with nothing already
    # active).
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False)

    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    # Chain start — set once, never changed across advances.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Reset to now() every time `level` advances — the "how long has
    # the *current* owner had this" clock, distinct from created_at.
    level_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Acknowledgment deadline for the current level — the sweep advances
    # (or, at SITE_LEAD, re-notifies) any ACTIVE row once this passes.
    ack_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    closed_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        # The sweep's overdue-acknowledgment query path:
        # WHERE status = 'ACTIVE' AND ack_due_at < :now.
        Index("ix_ticket_escalations_status_ack_due_at", "status", "ack_due_at"),
        # The sweep's handling-stage-breach query path (list_handling_
        # stage_overdue): WHERE handling_stage_due_at IS NOT NULL AND
        # handling_stage_due_at < :now.
        Index(
            "ix_ticket_escalations_handling_stage_due_at",
            "handling_stage_due_at",
            postgresql_where=(handling_stage_due_at.is_not(None)),
        ),
        # At most one non-CLOSED escalation per ticket at a time —
        # enforced in Postgres, not just application logic, so a race
        # between two concurrent escalate calls can't create two
        # active chains for the same ticket.
        Index(
            "ix_ticket_escalations_one_active_per_ticket",
            "ticket_id",
            unique=True,
            postgresql_where=(status != "CLOSED"),
        ),
    )

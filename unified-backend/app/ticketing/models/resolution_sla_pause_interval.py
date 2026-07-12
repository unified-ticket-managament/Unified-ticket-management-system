import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

#resolution_sla_pause_interval.py
class ResolutionSLAPauseInterval(Base):
    """
    Append-only audit ledger, child of ResolutionSLA — one row per
    pause/resume cycle, purely for human-readable reporting/
    transparency ("show every time this ticket waited on the customer
    and for how long"). Deliberately NEVER read by the breach sweep or
    the due_at shift math (see ResolutionSLA's own docstring) — this
    table could be deleted entirely without affecting SLA correctness,
    only historical visibility.

    One row is created at pause time and updated (not re-inserted) at
    resume time, so an in-progress pause is simply a row with
    `resumed_at IS NULL`.
    """

    __tablename__ = "resolution_sla_pause_intervals"

    pause_interval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    resolution_sla_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resolution_slas.resolution_sla_id"),
        nullable=False,
        index=True,
    )

    paused_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    resumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # WAITING_FOR_CLIENT_STATUS (automatic, from change_status) or
    # MANUAL_OVERRIDE (from the manual pause/resume action) — a free
    # string, like Interaction.interaction_type, since nothing filters
    # on it beyond human reporting.
    pause_reason: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    # The STATUS_CHANGE interaction (pause) or the inbound-reply/
    # STATUS_CHANGE interaction (resume) that triggered this
    # transition — for traceability. Left nullable since a manual
    # override pause/resume has no such interaction to point at other
    # than the SLA_PAUSED/SLA_RESUMED interaction itself, which isn't
    # created until after this row is written.
    triggering_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interactions.interaction_id"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_resolution_sla_pause_intervals_sla_id_paused_at",
            "resolution_sla_id",
            "paused_at",
        ),
    )

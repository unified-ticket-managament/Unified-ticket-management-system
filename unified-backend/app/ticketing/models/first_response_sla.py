import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

from app.ticketing.enums import SLAClockStatus, TicketPriority

#first_response_sla.py
class FirstResponseSLA(Base):
    """
    First Response SLA clock — 1:1 with a thread-ROOT Interaction
    (never a reply; see EmailService.receive_email's own thread-root
    guard). Starts the instant a new inbound thread arrives and
    completes the moment an Account Manager finishes triage (archive /
    reply / attach to an existing ticket / create a new ticket) — see
    `completion_reason` for which.

    `status` only ever moves PENDING -> COMPLETED (no pause concept —
    unlike Resolution, nothing pauses triage).
    """

    __tablename__ = "first_response_slas"

    first_response_sla_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    interaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interactions.interaction_id"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Denormalized off the interaction's own client_id so the breach
    # sweep can resolve notification recipients (the owning Account
    # Manager) without a join back to interactions/clients on every
    # tick.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.client_id"),
        nullable=True,
        index=True,
    )

    # Snapshotted at clock-creation time. Pre-ticket inbox items have
    # no priority field of their own, so this defaults to MEDIUM for
    # policy lookup — a known v1 limitation (see plan doc §1.2): it
    # only affects how urgently an at-risk/breached First Response
    # reads, never whether triage actually happened.
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
        default=SLAClockStatus.PENDING,
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

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # One of ARCHIVED / REPLIED / ATTACHED_TO_TICKET / TICKET_CREATED —
    # a free string (like Interaction.interaction_type) rather than a
    # native Postgres enum, since nothing queries/filters on it.
    completion_reason: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    # Populated for ATTACHED_TO_TICKET/TICKET_CREATED outcomes only —
    # lets reporting answer "how long did triage take before ticket X
    # existed" without joining back through the interaction.
    resulting_ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.ticket_id"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        # The breach sweep's primary query path:
        # WHERE status = 'PENDING' AND due_at < :now.
        Index("ix_first_response_slas_status_due_at", "status", "due_at"),
    )

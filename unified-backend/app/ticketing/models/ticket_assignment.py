import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

from app.ticketing.enums import TicketStatus

#ticket_assignment.py
class TicketAssignment(Base):
    """
    One user explicitly assigned to a ticket — the source of truth for
    multi-user assignment. A ticket may have any number of ACTIVE
    (removed_at IS NULL) assignments, at most one of them PRIMARY.

    PRIMARY vs SECONDARY is an accountability distinction only (the
    primary is who escalation and the legacy single-assignee views
    follow) — it never grants or denies an action; RBAC (see
    access_control.ensure_agent_can_act_on_ticket) stays the sole
    authority over what an assigned user may do.

    `status` is this assignee's OWN status — reuses ticket_status_enum
    so the vocabulary is identical to Ticket.current_status. Every
    status except CLOSED is individual: changing it touches only this
    row (and this row's own SLA run, see TicketAssignmentSLA). CLOSED
    is only ever written by the universal Close Ticket action, which
    closes every active assignment of the ticket in one transaction.

    Legacy projection (kept in sync by TicketAssignmentService, never
    written independently): Ticket.agent_id/assigned_by mirror the
    active PRIMARY row, and Ticket.current_status mirrors the primary
    row's status while the ticket is open — so a single-assignee
    ticket behaves exactly as it did before this table existed.

    Removal is a soft delete (removed_at/removed_by) so assignment and
    SLA history survive; re-adding the same user later creates a new
    row, which the partial unique index below permits.
    """

    __tablename__ = "ticket_assignments"

    assignment_id: Mapped[uuid.UUID] = mapped_column(
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

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )

    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    status: Mapped[TicketStatus] = mapped_column(
        SQLEnum(TicketStatus, name="ticket_status_enum", create_type=False),
        default=TicketStatus.OPEN,
        nullable=False,
    )

    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Stamped by the universal close only — cleared again on reopen,
    # same lifecycle as Ticket.closed_at/closed_by.
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    removed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
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
        # A user appears at most once among a ticket's ACTIVE
        # assignments — enforced in Postgres, not just the service.
        Index(
            "uq_ticket_assignments_active_user",
            "ticket_id",
            "user_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        # At most one active PRIMARY per ticket.
        Index(
            "uq_ticket_assignments_one_active_primary",
            "ticket_id",
            unique=True,
            postgresql_where=text("is_primary AND removed_at IS NULL"),
        ),
        # "Tickets assigned to me" (My Tickets tab/counts, assignee
        # filter) — the hot read path.
        Index(
            "ix_ticket_assignments_active_user_status",
            "user_id",
            "status",
            postgresql_where=text("removed_at IS NULL"),
        ),
    )

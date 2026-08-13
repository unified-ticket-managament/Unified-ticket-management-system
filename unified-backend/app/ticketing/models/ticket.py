import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

#ticket.py
from app.ticketing.enums import TicketPriority, TicketStatus
from shared_models.database import Base

if TYPE_CHECKING:
    from shared_models.models import User
    from .interaction import Interaction


class Ticket(Base):
    """
    Ticket Model
    """

    __tablename__ = "tickets"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Human-readable, permanent, sequential reference (displayed as
    # "TKT-<ticket_number>") — additional to, never a replacement for,
    # ticket_id above. Deliberately no Python-side `default`: this must
    # be assigned exactly once, atomically, by the database's own
    # `ticket_number_seq` sequence. `server_default` here is what tells
    # SQLAlchemy the column is populated by the DB itself and must be
    # omitted from the INSERT's column list (without it, the ORM sends
    # an explicit NULL for any column with no Python-side default,
    # violating this column's NOT NULL constraint) — the real
    # `DEFAULT nextval(...)` lives on the Postgres column itself (set
    # in the add_ticket_number migration), this just mirrors it so the
    # model matches reality. Never re-derived from sort order, so it
    # stays stable for the life of the ticket regardless of how many
    # other tickets are created later — see that migration for the
    # backfill of pre-existing rows.
    ticket_number: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        unique=True,
        server_default=text("nextval('ticket_number_seq')"),
    )

    # Legacy FK to an individual `users` row — kept nullable only so
    # existing rows created before the client-company model stay
    # valid. New tickets leave this NULL and use client_company_id
    # instead; do not write to this column going forward.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    # The client (company) this ticket belongs to. Ownership is the
    # company's Account Manager (clients.account_manager_id), not
    # this ticket's agent_id — agent_id is only "who is currently
    # working on it" (set via claim/transfer).
    client_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.client_id"),
        nullable=True,
        index=True,
    )

    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
        index=True,
    )

    # "Assigned By" — the user who performed the assignment action
    # (initial pre-assignment at ticket creation, a self-claim, or a
    # transfer) that produced the CURRENT agent_id above. Stamped
    # explicitly by every code path that writes agent_id (see
    # InteractionService.transfer_agent/claim_ticket and
    # InboxTicketService.create_ticket_from_interaction) — never
    # re-derived at read time. Deliberately distinct from: agent_id
    # (current assignee), created_by (who opened the ticket, if
    # different from whoever first assigned it), and any Reporting
    # Manager relationship (an unrelated org-chart concept —
    # ReportingManagerTeam). Nullable — NULL for a still-unclaimed
    # ticket, and left NULL by the migration that introduced this
    # column for any pre-existing ticket it couldn't confidently
    # backfill from the audit trail.
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    ticket_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    current_status: Mapped[TicketStatus] = mapped_column(
        SQLEnum(
            TicketStatus,
            name="ticket_status_enum",
        ),
        default=TicketStatus.OPEN,
        nullable=False,
        index=True,
    )

    current_priority: Mapped[TicketPriority] = mapped_column(
        SQLEnum(
            TicketPriority,
            name="ticket_priority_enum",
        ),
        default=TicketPriority.MEDIUM,
        nullable=False,
    )

    custom_fields: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Who closed the ticket (Close Ticket action) — cleared back to
    # None on reopen, same lifecycle as closed_at.
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # ------------------------

    interactions: Mapped[list["Interaction"]] = relationship(
        "Interaction",
        back_populates="ticket",
    )
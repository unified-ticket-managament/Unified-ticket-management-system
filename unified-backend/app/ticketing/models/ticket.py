import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

#ticket.py
from app.ticketing.enums import TicketPriority, TicketStatus
from shared_models.database import Base

if TYPE_CHECKING:
    from shared_models.models import User
    from .interaction import Interaction


# Which numbering generation a ticket's ticket_number belongs to.
# "legacy" = existed before the dual-series cutover (add_ticket_number_
# series_and_counter migration) and keeps whatever number it already
# had, forever. "current" = created after that cutover, numbered from
# TicketNumberCounter's own gapless, transactional 1, 2, 3, ... —
# completely independent of the legacy numbers, which is why the same
# integer can legitimately appear once per series (see the composite
# unique constraint below) — disambiguated only internally (this
# column, created_at, ticket_id), never in the displayed "TKT-<n>"
# label itself.
TICKET_NUMBER_SERIES_LEGACY = "legacy"
TICKET_NUMBER_SERIES_CURRENT = "current"
TICKET_NUMBER_SERIES_VALUES = (TICKET_NUMBER_SERIES_LEGACY, TICKET_NUMBER_SERIES_CURRENT)


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
    # ticket_id above. Deliberately no Python-side `default`.
    #
    # The real generation mechanism for a NEW ("current"-series) ticket
    # is NOT this column's server_default — it's
    # TicketRepository._allocate_current_ticket_number, which locks and
    # increments TicketNumberCounter's 'current' row inside the same
    # transaction as this row's INSERT (gapless: a rolled-back
    # transaction never burns a number, unlike a bare SEQUENCE). The
    # server_default below still points at the ORIGINAL
    # `ticket_number_seq` sequence purely as a harmless fallback for
    # code that constructs a Ticket directly without going through the
    # repository (several test fixtures do, for unrelated SLA/
    # escalation/attachment setup) — it is never used for a real,
    # user-initiated ticket creation. No longer `unique=True` on its
    # own: see the composite constraint in __table_args__, which scopes
    # uniqueness per ticket_number_series instead of globally, since
    # legacy and current tickets are independently-numbered and may
    # legitimately share an integer.
    ticket_number: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("nextval('ticket_number_seq')"),
    )

    # See TICKET_NUMBER_SERIES_* above. Deliberately no Python-side
    # `default` either — same reasoning as ticket_number. Defaults to
    # "legacy" (not "current") at the DB level so anything that bypasses
    # TicketRepository.create() (again, mostly test fixtures) never
    # lands in the gapless "current" number-space it doesn't need or
    # want to be part of; the real creation path always sets this
    # explicitly to "current".
    ticket_number_series: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'legacy'"),
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

    __table_args__ = (
        # Same integer is legal once per series (legacy vs current —
        # they're numbered from two independent, never-reconciled
        # sources) but still forbidden twice within the same series,
        # exactly as strict as the single-column constraint this
        # replaces. Column order is (ticket_number, ticket_number_series)
        # and not the reverse: TicketRepository's TKT-<n> search filters
        # only on ticket_number, and a leading-column equality filter is
        # what lets Postgres use this index efficiently for that lookup.
        UniqueConstraint(
            "ticket_number", "ticket_number_series",
            name="uq_tickets_ticket_number_series",
        ),
        CheckConstraint(
            f"ticket_number_series IN {TICKET_NUMBER_SERIES_VALUES!r}",
            name="ck_tickets_ticket_number_series",
        ),
    )
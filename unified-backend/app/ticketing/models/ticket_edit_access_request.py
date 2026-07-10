import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

from app.ticketing.enums import EditAccessStatus


class TicketEditAccessRequest(Base):
    """
    A request from an agent who isn't the ticket's assigned agent (and
    doesn't hold the blanket ticket:editother_ticket permission) to work on
    this one specific ticket alongside whoever else already can.
    Reviewed by anyone who already holds ticket:editother_ticket for the
    ticket's scope (see access_control.ensure_can_review_edit_access).

    Approving sets status=APPROVED and optionally expires_at; the
    active-grant check elsewhere is simply
    "status == APPROVED and (expires_at is None or expires_at > now())" —
    no separate revoke concept exists here, matching what was asked
    for (request/approve/reject only).
    """

    __tablename__ = "ticket_edit_access_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tickets.ticket_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )

    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[EditAccessStatus] = mapped_column(
        SQLEnum(
            EditAccessStatus,
            name="edit_access_status_enum",
        ),
        default=EditAccessStatus.PENDING,
        nullable=False,
    )

    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    review_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        # At most one PENDING request per ticket+requester at a time —
        # doesn't block a fresh request after a prior one was
        # rejected, since that row is no longer PENDING.
        Index(
            "ix_ticket_edit_access_requests_pending_unique",
            "ticket_id",
            "requested_by",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

#client.py
class Client(Base):
    """
    A client company onboarded onto the platform, identified by a
    real email address stored in `inbox_email`. How that address is
    matched against an inbound email depends on where the email
    arrived (see EmailService.receive_email / is_configured_graph_mailbox):

    - Mail arriving at the one configured Microsoft Graph shared
      mailbox (every real client today) is matched by the message's
      `from` address — `inbox_email` here is the client's own real
      address (e.g. gogineni@painmedpa.com), since every client sends
      into the same shared mailbox and the `to` address can no longer
      distinguish them.
    - Mail arriving at any other, legacy dedicated-inbox-per-client
      address (e.g. a still-dummy demo client never migrated off the
      pre-Graph setup) is matched by the message's `to` address
      instead — `inbox_email` there is that dedicated address.

    Either way, a match hands the email to the owning Account Manager
    (`account_manager_id`).

    Deliberately NOT the same thing as a `users` row: a client here
    is a company, not an individual — any number of people at that
    company can email in, matched to the same Client if their address
    is the one stored here.
    """

    __tablename__ = "clients"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # Always stored lowercased so lookups are a plain equality match.
    inbox_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
    )

    account_manager_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
        index=True,
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

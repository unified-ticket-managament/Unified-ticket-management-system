import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


class ClientContact(Base):
    """
    A known contact email address for a client company — distinct from
    `Client.inbox_email` (the single address inbound mail is matched
    against) and from `ClientContactResponse` (computed on the fly from
    `Interaction.from_email` for the ticket workspace's "who's emailed
    in" view). Added for the real-org-data migration: real clients have
    several known contacts, which the original schema had nowhere to
    store ahead of any ticket ever arriving from them. `is_primary`
    marks the one contact promoted to `Client.inbox_email` at seed time.
    """

    __tablename__ = "client_contacts"

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.client_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Always stored lowercased so lookups are a plain equality match,
    # same convention as Client.inbox_email.
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
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

    __table_args__ = (
        UniqueConstraint("client_id", "email", name="uq_client_contact_email"),
    )

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


class ClientContact(Base):
    """
    A known contact email address for a client company — an individual
    employee/contact at that company, always distinct from
    `Client.inbox_email` (the client's own official distribution/
    intake address; see that model's docstring). Every one of a
    client's configured contact emails belongs here — none of them is
    ever the same address as `Client.inbox_email`, and the org-data
    import (scripts/org_seed/) actively excludes a client's
    distribution email from this table even if it happened to appear
    in the source contact list. Distinct too from `ClientContactResponse`
    (computed on the fly from `Interaction.from_email` for the ticket
    workspace's "who's emailed in" view, then merged with this table's
    rows — see `ClientService.list_contacts`).

    `is_primary` no longer means "promoted to `Client.inbox_email`" —
    that concept doesn't exist anymore now that the distribution
    email is a curated, explicit value never derived from a contact
    (see `scripts/org_seed/mapping.resolve_distribution_email`). The
    org-data import always leaves it `False`; the column is kept for
    any other caller that wants to flag one contact as more
    significant than the rest, independent of `inbox_email`.
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

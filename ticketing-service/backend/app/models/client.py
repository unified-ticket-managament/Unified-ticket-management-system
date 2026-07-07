import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

#client.py
class Client(Base):
    """
    A client company onboarded onto the platform, identified by the
    dedicated shared inbox address it was given at onboarding (e.g.
    abc@probeps.com). Every inbound email is routed by matching its
    `to` address against `inbox_email` here, then handed to the
    owning Account Manager.

    Deliberately NOT the same thing as a `users` row: a client here
    is a company, not an individual — any number of people at that
    company can email the shared inbox.
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

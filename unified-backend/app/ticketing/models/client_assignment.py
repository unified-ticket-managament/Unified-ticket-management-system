import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

AR_LEAD = "AR_LEAD"
CODING_LEAD = "CODING_LEAD"
POSTING_LEAD = "POSTING_LEAD"
LEAD_ROLES = (AR_LEAD, CODING_LEAD, POSTING_LEAD)


class ClientAssignment(Base):
    """
    A per-client AR/Coding/Posting Lead assignment — separate from
    `Client.account_manager_id` (the single owning Account Manager).
    Added for the real-org-data migration: real clients have a lead
    per function on top of one account manager, which the original
    schema had no room for. If a client's source data listed no lead
    for a given role, that role's row here falls back to the client's
    own Account Manager (see scripts/org_seed) rather than being left
    unassigned.
    """

    __tablename__ = "client_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
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

    lead_role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
        UniqueConstraint("client_id", "lead_role", name="uq_client_assignment_role"),
        CheckConstraint(
            f"lead_role IN {LEAD_ROLES!r}",
            name="ck_client_assignment_lead_role",
        ),
    )

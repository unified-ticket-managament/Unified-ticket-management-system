import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


class DistributionList(Base):
    """
    A named, internal-user-only recipient group ("APM Support Team")
    usable anywhere a recipient can be picked — Manual Forward, Rules'
    forward_to action, Mail Reply/Compose, Ticket Reply, and Internal
    Note. Always resolved to its *current* active members at send
    time (DistributionListRepository.get_active_member_emails_by_list_ids)
    — never a snapshot, so membership changes take effect immediately
    with no caller (a saved Rule, a composed draft) needing an edit.

    `name` uniqueness is enforced case-insensitively via a functional
    index (see the accompanying migration) rather than a plain
    `unique=True` column constraint, so "APM Support Team" and "apm
    support team" can't both exist.
    """

    __tablename__ = "distribution_lists"

    distribution_list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
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


class DistributionListMember(Base):
    """
    Membership join table — a real table with its own surrogate PK
    (matching ReportingManagerTeam's convention), not a bare
    association Table, since members need to be added/removed/
    validated individually. Members must be existing internal UTMS
    users (validated against AGENT_ROLE_NAMES at add-member time in
    DistributionListService) — never an external email.
    """

    __tablename__ = "distribution_list_members"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    distribution_list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("distribution_lists.distribution_list_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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

    __table_args__ = (
        UniqueConstraint(
            "distribution_list_id",
            "user_id",
            name="uq_distribution_list_member",
        ),
    )

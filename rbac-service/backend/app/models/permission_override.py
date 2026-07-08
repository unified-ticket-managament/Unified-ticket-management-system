import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_models.database import Base

if TYPE_CHECKING:
    from app.models.permission import Permission


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserPermissionOverride(Base):
    """
    A capability granted to one specific user, beyond whatever their
    role already grants. Purely additive — grant() rejects a permission
    the target's role already includes, so this table can never be used
    to take something away from a role's default bundle, only to hand a
    single person something extra.

    Soft-revoked (revoked_at/revoked_by) rather than deleted so the
    grant/revoke history survives, and the partial unique index below
    only constrains *active* rows, so the same permission can be
    granted, revoked, and re-granted to the same user over time.
    """

    __tablename__ = "user_permission_overrides"

    override_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("permissions.permission_id", ondelete="CASCADE"),
        nullable=False,
    )

    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    permission: Mapped["Permission"] = relationship(
        "Permission",
    )

    __table_args__ = (
        Index(
            "ix_user_permission_overrides_active_unique",
            "user_id",
            "permission_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

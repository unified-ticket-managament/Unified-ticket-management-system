# impersonation_session.py

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_models.database import Base

if TYPE_CHECKING:
    from shared_models.models import User


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ImpersonationSession(Base):
    """
    A bounded, database-backed "Login as User" session — the actor
    (a Super Admin) temporarily operates the app with the target's
    identity/permissions. Deliberately separate from the stateless JWT
    access/refresh tokens: those alone can't be revoked early (a token
    is valid until it expires, full stop), so app/dependencies/auth.py
    checks this row on every request carrying an
    `impersonation_session_id` claim, in addition to normal JWT
    validation — see that module's docstring for the exact check.

    actor_user_id/target_user_id are nullable + ON DELETE SET NULL
    (survive account deletion as a historical record), mirroring
    UserPermissionOverride.granted_by/revoked_by's existing precedent
    in this same codebase — enforced NOT NULL at creation time by
    ImpersonationService, not by the column itself.
    """

    __tablename__ = "impersonation_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # "ACTIVE" | "ENDED" — no background sweeper marks a naturally
    # time-expired row as "ENDED"; the per-request check in
    # app/dependencies/auth.py independently enforces
    # `now < expires_at` regardless of this column, so a stale
    # "ACTIVE" row past its own expires_at is still correctly rejected.
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ACTIVE",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    actor: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[actor_user_id],
        viewonly=True,
    )

    target: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[target_user_id],
        viewonly=True,
    )

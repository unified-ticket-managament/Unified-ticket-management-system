import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_models.database import Base

if TYPE_CHECKING:
    from app.rbac.models.permission import Permission
    from app.rbac.models.permission_override import UserPermissionOverride


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PermissionRequestStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class PermissionRequest(Base):
    """
    A user's self-service ask for a permission they don't currently
    hold, addressed to a specific role (e.g. "Account Manager") for
    review. Deliberately separate from UserPermissionOverride: this
    table tracks the *request's own lifecycle* (pending/approved/
    rejected, who reviewed it, their comment); the actual grant, once
    approved, is created through the existing PermissionOverrideService
    .grant() and linked back via granted_override_id — this table never
    duplicates override/grant logic, only the request/review workflow
    around it. A plain string status column (not a native Postgres
    enum) since this is a new, isolated table with no legacy rows to
    reconcile against.

    "Who can review this" is resolved the same way
    PermissionOverrideService._ensure_can_manage_overrides already
    does (Super Admin/Site Lead unconditional, Account Manager scoped
    to their own reports) — requested_role only narrows *which* role's
    members should see it in their queue, it isn't itself an
    authorization boundary; approve()/reject() still re-check real
    authority before acting.
    """

    __tablename__ = "permission_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    requester_id: Mapped[uuid.UUID] = mapped_column(
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

    requested_role: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # The specific person picked in the "Request To" dropdown — the
    # real routing/authorization key as of this column's introduction.
    # requested_role is kept purely as an immutable display snapshot
    # (the approver's role name at request time); it no longer decides
    # who can see or act on the request. Nullable only because rows
    # created before this column existed have no way to backfill a
    # specific person — those legacy rows simply become unreachable
    # from "Pending My Review" (see PermissionRequestService), which
    # is an acceptable one-time transitional gap, never a crash.
    selected_approver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Set only for a request that should grant the permission for one
    # specific ticket rather than everywhere (see the matching column
    # on UserPermissionOverride) — carried through to the resulting
    # override unchanged at approval time. Plain UUID, no FK, for the
    # same cross-domain-migration reason documented there.
    scope_ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default=PermissionRequestStatus.PENDING,
        nullable=False,
        index=True,
    )

    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    review_comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    granted_override_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("user_permission_overrides.override_id", ondelete="SET NULL"),
        nullable=True,
    )

    # Revocation — deliberately tracked on the request itself rather
    # than read off granted_override's own revoked_at/revoked_by, so
    # this row's audit trail stays self-contained and independent of
    # the override implementation detail underneath it. Approving,
    # then revoking, never deletes this row (see module docstring).
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    revoke_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    permission: Mapped["Permission"] = relationship(
        "Permission",
    )

    granted_override: Mapped["UserPermissionOverride | None"] = relationship(
        "UserPermissionOverride",
        viewonly=True,
    )

    __table_args__ = (
        # At most one open request per requester+permission(+ticket
        # scope) at a time — doesn't block a fresh request after a
        # prior one was decided (no longer PENDING), and COALESCE's
        # scope_ticket_id to a sentinel so two *global* requests still
        # collide while two distinct ticket-scoped requests for the
        # same permission (different tickets) don't.
        Index(
            "ix_permission_requests_pending_unique",
            "requester_id",
            "permission_id",
            text(
                "COALESCE(scope_ticket_id, "
                "'00000000-0000-0000-0000-000000000000'::uuid)"
            ),
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

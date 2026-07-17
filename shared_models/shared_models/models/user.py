import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_models.database import Base
from shared_models.mixins import TimestampMixin

if TYPE_CHECKING:
    from .category import Category
    from .role import Role


class User(TimestampMixin, Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.role_id"),
        nullable=False,
    )

    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    teamlead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    # Work-specialization category (Eligibility, AR, Claims, ...) —
    # nullable because only Staff/Team Lead are expected to have one;
    # every other role (and every pre-existing user, before this
    # column existed) legitimately has none. Enforced as required for
    # Staff/Team Lead at the application layer, not via a DB
    # constraint, same pattern as manager_id/teamlead_id above.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.category_id"),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Bumped whenever anything auth-relevant about this user changes
    # (role/category/manager/teamlead reassignment, activation state,
    # a personal permission override grant/revoke) or whenever their
    # role's own permission set changes (a bulk UPDATE across every
    # user sharing that role_id — see RolePermissionService). Embedded
    # in the JWT at login/refresh time and used as part of the
    # in-memory RBAC cache's key (app/core/rbac_cache.py): a cached
    # "this session is still valid" entry is keyed on
    # (user_id, permission_version), so bumping this column doesn't
    # require touching the cache at all — it just means the next time
    # that user's token is checked against the DB, the versions won't
    # match and the stale session is rejected. Never decremented.
    permission_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )

    # -------------------------
    # Profile fields (Profile page — see root CLAUDE.md's
    # "Profile module" pass). All nullable: every one predates this
    # column existing, so a pre-existing user legitimately has no
    # value yet until they (or a backfill) set one. `department`/
    # `team` are deliberately plain free-text columns, independent of
    # `category_id` above — that column still drives real RBAC/ticket-
    # routing business logic and is never touched by the Profile
    # page's own edit form; these two exist purely for profile
    # display/self-editing (department) and display only (team, no
    # edit surface reads/writes it).
    # -------------------------

    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)

    alternate_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    phone_number: Mapped[str | None] = mapped_column(String(30), nullable=True)

    office_location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    department: Mapped[str | None] = mapped_column(String(100), nullable=True)

    team: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Preference fields — nullable with a server-side default matching
    # what the frontend's client-only store used to default these to,
    # so an existing user's effective preference doesn't change the
    # moment these become DB-backed.
    language: Mapped[str | None] = mapped_column(
        String(10), nullable=True, server_default="en"
    )

    date_format: Mapped[str | None] = mapped_column(
        String(20), nullable=True, server_default="MM/DD/YYYY"
    )

    time_format: Mapped[str | None] = mapped_column(
        String(10), nullable=True, server_default="12h"
    )

    time_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    default_dashboard: Mapped[str | None] = mapped_column(
        String(50), nullable=True, server_default="Dashboard"
    )

    # -------------------------
    # Relationships
    # -------------------------

    role: Mapped["Role"] = relationship(
        "Role",
        back_populates="users",
    )

    manager: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[manager_id],
        remote_side=[user_id],
        post_update=True,
    )

    teamlead: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[teamlead_id],
        remote_side=[user_id],
        post_update=True,
    )

    category: Mapped["Category | None"] = relationship(
        "Category",
        back_populates="users",
    )
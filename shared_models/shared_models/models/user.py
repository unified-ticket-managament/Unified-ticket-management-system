import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_models.database import Base
from shared_models.mixins import TimestampMixin
from shared_models.models.user_category import user_categories

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

    # Organization-Chart-only reporting relationship — deliberately
    # separate from manager_id/teamlead_id above, which continue to
    # drive every existing permission-scoping/SLA/escalation/ticket-
    # assignment consumer unchanged (see OrganizationService's own
    # docstring). Unrestricted by role: any user may be any other
    # user's reporting_manager_id, since the Organization Chart must
    # reflect the real reporting line as-is, not one inferred from
    # role names. Nullable (a top-of-company user has none) and
    # initially backfilled from manager_id/teamlead_id by
    # alembic_rbac's add_reporting_manager_id_to_users migration —
    # editable independently of both going forward.
    reporting_manager_id: Mapped[uuid.UUID | None] = mapped_column(
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

    # Whether this user is currently on leave — a display-only
    # indicator (see the Leave toggle in the user profile/detail view)
    # never enforced as an eligibility/authorization rule anywhere: a
    # user on leave still appears, selectable, in every ticket
    # create/assign/transfer and permission-request picker, just
    # annotated "(Leave)". Deliberately independent of is_active/
    # permission_version — toggling it is not an authorization change.
    is_on_leave: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        server_default="false",
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

    # Real-world job title (e.g. "Sr. AR Associate", "Team Lead - AR"),
    # distinct from `role_id`'s fixed RBAC ladder and from `category_id`'s
    # ticket-routing category — display only, never read by any
    # permission/routing check. See
    # e8566a9089a3_add_designation_to_users.py.
    designation: Mapped[str | None] = mapped_column(String(150), nullable=True)

    # The official, human-readable Employee ID from the company's HR/
    # payroll master data (e.g. "266", "2") — deliberately NOT the
    # primary/foreign key anywhere; `user_id` (UUID) remains the sole
    # canonical identifier for every relationship (assignment,
    # ownership, audit, reporting hierarchy, authentication). This is
    # an additional, purely display/search identifier layered on top,
    # stored as the exact string the official source gives (never
    # zero-padded or otherwise reformatted, never derived from the
    # UUID, never invented for an account with no official record —
    # see scripts/org_seed/backfill_employee_number.py, the one-time,
    # non-destructive script that populates it for already-imported
    # real employees by matching source_data.py's EMPLOYEES against
    # this table's existing rows). Nullable and unique: most demo/
    # system accounts (Super Admin, local dev fixtures, ...) have no
    # official employee record and therefore no value here.
    employee_number: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True
    )

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

    reporting_manager: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[reporting_manager_id],
        remote_side=[user_id],
        post_update=True,
    )

    category: Mapped["Category | None"] = relationship(
        "Category",
        back_populates="users",
    )

    # Many-to-many category membership — a user (most commonly a Team
    # Lead) may belong to several work-specialization categories at
    # once. Additive alongside `category_id`/`category` above, which
    # stay in place as a "legacy primary category" (kept in sync by
    # UserService.set_user_categories, never derived automatically by
    # the ORM) for any consumer not yet updated to read this
    # collection. See root CLAUDE.md's multi-category-users section.
    categories: Mapped[list["Category"]] = relationship(
        "Category",
        secondary=user_categories,
        # `user_categories` has two FKs into `users` (`user_id` and
        # `assigned_by`) — explicit join conditions needed since
        # SQLAlchemy can't infer which one backs this relationship.
        primaryjoin="User.user_id == user_categories.c.user_id",
        secondaryjoin="Category.category_id == user_categories.c.category_id",
        back_populates="assigned_users",
    )
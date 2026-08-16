from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Table
from sqlalchemy.dialects.postgresql import UUID

from shared_models.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Many-to-many User <-> Category join table, backing `User.categories`/
# `Category.assigned_users` below. A plain `Table` (no mapped class) —
# nothing needs to query a join row as a first-class entity, it exists
# purely to back a `secondary=` relationship, so a composite primary key
# on the two FK columns is the identity itself rather than a surrogate
# id + separate unique constraint (contrast with `ReportingManagerTeam`,
# which IS queried directly via its own repository and has no ORM
# `relationship()` at all).
#
# `users.category_id`/`User.category` (the pre-existing scalar FK/
# relationship) are deliberately left untouched and still work exactly
# as before — this table is additive, not a replacement. See root
# CLAUDE.md and the multi-category-users design for the full rationale.
user_categories = Table(
    "user_categories",
    Base.metadata,
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "category_id",
        UUID(as_uuid=True),
        ForeignKey("categories.category_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
    Column(
        "assigned_by",
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column(
        "assigned_at",
        DateTime(timezone=True),
        default=_utc_now,
        nullable=False,
    ),
)

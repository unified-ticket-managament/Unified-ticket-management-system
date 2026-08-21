import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_models.database import Base
from shared_models.models.user_category import user_categories

if TYPE_CHECKING:
    from .user import User


class Category(Base):
    """
    A work-specialization category for Staff/Team Lead users (e.g.
    AR, Referral, Coding, ...) — lets tickets be filtered/assigned by
    the category a user works. Not a ticket's own status or priority.

    `category_name` used to be a native Postgres ENUM
    (`category_name_enum`, backed by a fixed Python `CategoryName`
    enum) — every new category required a code change plus an
    `ALTER TYPE ... ADD VALUE` migration. It's now a plain, unique,
    indexed string: categories are created at runtime through the
    normal Category CRUD API (see app/rbac/services/category_service.py),
    with no code change or migration needed per new category. See
    alembic_rbac's category_name_enum_to_varchar migration.
    """

    __tablename__ = "categories"

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    category_name: Mapped[str] = mapped_column(
        String(150),
        unique=True,
        nullable=False,
        index=True,
    )

    users: Mapped[list["User"]] = relationship(
        "User",
        back_populates="category",
    )

    # Reverse side of User.categories (many-to-many) — named
    # `assigned_users`, not `users`, so it never collides with the
    # scalar-FK relationship above (which still backs the legacy
    # singular `category_id`/`category`).
    assigned_users: Mapped[list["User"]] = relationship(
        "User",
        secondary=user_categories,
        # See User.categories' matching comment — `user_categories` has
        # two FKs into `users`, so the join conditions must be explicit.
        primaryjoin="Category.category_id == user_categories.c.category_id",
        secondaryjoin="User.user_id == user_categories.c.user_id",
        back_populates="categories",
    )

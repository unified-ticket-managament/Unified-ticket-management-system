import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
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
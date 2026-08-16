import uuid
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_models.database import Base
from shared_models.models.user_category import user_categories

if TYPE_CHECKING:
    from .user import User


class CategoryName(str, Enum):
    """
    Fixed work-specialization category names — a native Postgres ENUM
    (see the `category_name_enum` SQLEnum below), matching the
    pattern ticketing-service uses for TicketStatus/TicketPriority.
    Adding a category means adding a member here AND a migration
    (`ALTER TYPE category_name_enum ADD VALUE ...`), same as that
    service's add-postgres-enum-value skill — this is a deliberate
    tradeoff of the fixed list not needing a lookup at Postgres's
    read layer, at the cost of every new category needing a migration.

    Replaced outright (not extended) by
    alembic_rbac's d3f5a7b9c1e3_replace_category_names_for_real_org_data
    — the original 7 values (Eligibility, Patient Calling, AR, Payment
    Posting, PA, Charge Entry, Claims) didn't match the real
    organization's actual "Process" values except AR and Payment
    Posting, so the whole set was swapped for the real 8 processes
    rather than layered on top of the dummy ones.
    """

    AR = "AR"
    REFERRAL = "Referral"
    AUTHORIZATION = "Authorization"
    IV = "IV"
    CREDENTIALING = "Credentialing"
    CODING = "Coding"
    PAYMENT_POSTING = "Payment Posting"
    QUALITY = "Quality"


class Category(Base):
    """
    A work-specialization category for Staff/Team Lead users (e.g.
    Eligibility, AR, Claims) — lets tickets be filtered/assigned by
    the category a user works. Not a ticket's own status or priority.
    """

    __tablename__ = "categories"

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    category_name: Mapped[CategoryName] = mapped_column(
        SQLEnum(
            CategoryName,
            name="category_name_enum",
            # Store/compare the enum's *value* ("Patient Calling"),
            # not its Python member name ("PATIENT_CALLING") — names
            # with spaces can't be valid Python identifiers, so name
            # and value deliberately differ here (unlike ticketing-
            # service's enums, where they're identical).
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
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

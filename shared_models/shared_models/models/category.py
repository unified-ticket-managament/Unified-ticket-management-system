import uuid
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_models.database import Base

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
    """

    ELIGIBILITY = "Eligibility"
    PATIENT_CALLING = "Patient Calling"
    AR = "AR"
    PAYMENT_POSTING = "Payment Posting"
    PA = "PA"
    CHARGE_ENTRY = "Charge Entry"
    CLAIMS = "Claims"


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

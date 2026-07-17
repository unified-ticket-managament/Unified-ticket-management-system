import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReportingManagerTeam(Base):
    """
    Maps an Account Manager as the "Reporting Manager" for one or more
    business categories (Eligibility, AR, ...) — an additional HR/
    people-management responsibility layered onto an existing Account
    Manager, not a separate role (see root CLAUDE.md's "Organization
    Structure" section). Deliberately separate from both:

    - `User.manager_id` (the real org-chart "who does this Team Lead
      report to" reporting line), and
    - ticket-assignment capability (unrestricted Account Manager ->
      any Team Lead, see AssignmentService/InteractionService).

    Three independent concepts that must never collapse into one
    column. Genuinely many-to-many: one Account Manager can be
    Reporting Manager for several categories, and nothing here caps a
    category to a single Reporting Manager either — the business
    examples only ever use one per category, but that's a data fact,
    not a constraint this table enforces ("the communication many-to-
    many or one-to-many should be dynamic", not hardcoded).
    """

    __tablename__ = "reporting_manager_teams"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    account_manager_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.category_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "account_manager_id",
            "category_id",
            name="uq_reporting_manager_team",
        ),
    )

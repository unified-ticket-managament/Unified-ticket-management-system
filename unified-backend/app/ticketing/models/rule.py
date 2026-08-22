import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base


class Rule(Base):
    """
    One generic table for both Mail Rules and OTP Rules (deliberately
    not two separate tables — both are "Email Received -> IF -> THEN",
    differing only in which conditions/actions are valid, which is
    enforced at the schema layer via rule_enums.py, not the DB schema).

    `conditions`/`exceptions` share one shape:
    {"combinator": "AND"|"OR", "rules": [{"field", "operator", "value"}]}
    — a flat list joined by a single combinator, matching the rule
    builder's own "add another condition, then choose AND/OR" flow
    (no nested groups). `exceptions` uses the same shape and, when its
    own `rules` list is non-empty and matches, suppresses an otherwise-
    matching rule — Outlook's own "except if" semantics.

    `actions` is an ordered JSON array — array order is execution
    order. `priority` is dense *within a category* (Mail Rules and OTP
    Rules each have their own 1..N ordering) since the engine always
    evaluates every enabled Mail Rule before any OTP Rule.
    """

    __tablename__ = "rules"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # RuleCategory.MAIL_RULE / RuleCategory.OTP_RULE — plain string,
    # not a native enum (see rule_enums.py's own docstring).
    category: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)

    exceptions: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=lambda: {"combinator": "AND", "rules": []}
    )

    actions: Mapped[list] = mapped_column(JSONB, nullable=False)

    stop_processing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Dense per-category evaluation order (1-based). Maintained by the
    # reorder endpoint, not user-typed — see RuleRepository.reorder.
    priority: Mapped[int] = mapped_column(Integer, nullable=False)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=True,
    )

    # Every explicitly added/shared/assigned user's id, as strings —
    # same JSONB-list-of-UUID-strings shape as TicketEscalation.owner_ids.
    # A rule with an empty list here is private to created_by; this is
    # the ONLY thing (besides created_by itself, or rule:view_all) that
    # widens who may view/manage it. Never populated from a rule's own
    # forward_to action recipients — those are a forwarding destination,
    # not a grant of rule/folder access.
    shared_user_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

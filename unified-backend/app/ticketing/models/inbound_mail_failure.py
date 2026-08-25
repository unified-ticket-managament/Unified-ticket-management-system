import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

#inbound_mail_failure.py


class InboundMailFailure(Base):
    """
    Phase 2 hardening: a persisted, queryable record of inbound-mail
    processing failures — backs, but does not replace, the poller's
    own in-memory `_PollState.failure_counts` (graph_mail_poller.py),
    which is what actually drives the retry/dead-letter decision and
    resets on every process restart. This table exists purely so ops
    staff can see "this message has been failing" even after a
    restart, or across the webhook transport (which has no in-memory
    retry counter of its own at all).

    Written to by both graph_mail_poller.py and
    app/ticketing/api/mail_integration.py whenever either hits a
    genuine processing failure (never for the benign duplicate-
    message-id race — see mail_integrity.is_duplicate_message_id_violation,
    which must be checked first) — upserted via `record_or_increment`,
    resolved via `mark_resolved` on eventual success.
    """

    __tablename__ = "inbound_mail_failures"

    inbound_mail_failure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    message_id: Mapped[str] = mapped_column(String(255), nullable=False)

    mailbox_address: Mapped[str] = mapped_column(String(255), nullable=False)

    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    attempt_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index(
            "ux_inbound_mail_failures_message_mailbox",
            "message_id",
            "mailbox_address",
            unique=True,
        ),
    )

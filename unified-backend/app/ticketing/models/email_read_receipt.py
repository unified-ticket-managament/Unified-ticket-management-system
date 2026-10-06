import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

# The only two states a tracked recipient can be in today. A real
# "declined" receipt has never been observed live, so no such state
# exists yet — the raw MDN `Disposition` is preserved in `disposition`
# so a future mapping can be added without losing data. Deliberately
# no "READ"/"UNREAD" vocabulary: a missing receipt never means unread.
RECEIPT_STATUS_REQUESTED = "REQUESTED"
RECEIPT_STATUS_CONFIRMED = "CONFIRMED"


class EmailReadReceipt(Base):
    """
    Per-recipient Outlook-style read-receipt (RFC 8098 MDN) state for
    one OUTBOUND interaction. One row per To/Cc recipient of a message
    sent with a receipt requested (never Bcc), created as REQUESTED
    once the send succeeded and moved to CONFIRMED when a matching
    receipt arrives (see read_receipt_service.py).

    This is NOT the agent-side `message_read_receipts` table (which
    records that a *user of this platform* opened a thread) — it
    records that a *recipient's mail system* acknowledged a message.
    A receipt is optional and recipient-controlled: absence of one
    never means the message was unread.

    Stores recipient, disposition and timestamps only — never the MDN
    body, quoted content or the original subject.
    """

    __tablename__ = "email_read_receipts"

    __table_args__ = (
        UniqueConstraint(
            "interaction_id",
            "recipient_email",
            name="uq_email_read_receipts_interaction_recipient",
        ),
        # Second idempotency guard: a receipt is never stored as an
        # Interaction, so the interactions.message_id duplicate check
        # never sees one. Partial — REQUESTED rows have no MDN yet.
        Index(
            "uq_email_read_receipts_mdn_message_id",
            "mdn_message_id",
            unique=True,
            postgresql_where=text("mdn_message_id IS NOT NULL"),
        ),
    )

    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    interaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interactions.interaction_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Lower-cased address of the tracked To/Cc recipient.
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=RECEIPT_STATUS_REQUESTED,
        server_default=RECEIPT_STATUS_REQUESTED,
    )

    # The receipt's own Date header (when available) — "receipt time",
    # NOT proof of the exact moment a person opened the message.
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Raw MDN `Disposition` field, preserved verbatim.
    disposition: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The receipt message's own RFC Message-ID (idempotency only).
    mdn_message_id: Mapped[str | None] = mapped_column(String(998), nullable=True)

    # Graph's receivedDateTime for the receipt.
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text("now()"),
        nullable=False,
    )

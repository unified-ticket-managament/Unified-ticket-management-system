from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared_models.database import Base

#mailbox_poll_state.py


class MailboxPollState(Base):
    """
    Persisted counterpart to graph_mail_poller.py's in-memory-only
    `_PollState` — one row per polled mailbox address (the legacy
    shared mailbox, plus every active Client.inbox_email/Category.
    inbox_email `_resolve_mailboxes_to_poll` returns). Exists because
    `_PollState.checkpoints` resets to a 15-minute lookback on every
    process restart, permanently losing anything older that hadn't
    been polled yet — this table lets a fresh process resume from
    where the last one left off instead.

    `checkpoint_at` is the same value `_PollState.checkpoints` holds
    in memory — advanced identically (including the "hold back to just
    before the earliest still-retryable failure" logic). Written on
    every successful tick's checkpoint update, not only on a change,
    so `last_success_at` also reflects "the poller is alive and
    reaching this mailbox", independent of whether any new mail
    happened to arrive that tick.

    `consecutive_failures`/`last_failure_at`/`last_failure_summary`/
    `last_alerted_at` back the mailbox-level stall alert (distinct
    from `inbound_mail_failures`, which is per-*message*, not
    per-mailbox — a whole-mailbox Graph fetch failure, e.g. a 403/404
    before any message is even listed, never reaches that table at
    all). Purely additive to the existing `exists_by_message_id`
    dedupe safety net in EmailService.receive_email — a stale or
    unwritten checkpoint here only ever widens the re-fetch window on
    the next process start, which that dedupe already tolerates.
    """

    __tablename__ = "mailbox_poll_state"

    mailbox_address: Mapped[str] = mapped_column(
        String(255),
        primary_key=True,
    )

    checkpoint_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_failure_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    last_alerted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

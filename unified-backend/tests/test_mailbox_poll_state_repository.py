# test_mailbox_poll_state_repository.py
#
# Round-trip coverage for MailboxPollStateRepository — the persisted
# counterpart to graph_mail_poller.py's in-memory _PollState (Fix 2/3
# of the mail-ingestion-reliability investigation). See
# tests/test_graph_mail_poller_multi_mailbox.py for the pure-logic
# poller-level tests using a fake of this repository; this file is
# the real thing against the real (dev) database, inside a transaction
# always rolled back at the end — same convention as
# test_ticket_attachments.py.

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.repositories.mailbox_poll_state_repository import (
    MailboxPollStateRepository,
)


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


def _mailbox() -> str:
    # Unique per test run so parallel/repeated runs never collide on
    # the primary key, without needing any cleanup logic beyond the
    # fixture's own rollback.
    return f"pollstate-test-{uuid.uuid4().hex}@example.com"


async def test_record_success_then_get_all_checkpoints_round_trips(db_session):
    repo = MailboxPollStateRepository(db_session)
    mailbox = _mailbox()
    checkpoint = datetime.now(timezone.utc) - timedelta(minutes=5)

    await repo.record_success(mailbox_address=mailbox, checkpoint_at=checkpoint)

    checkpoints = await repo.get_all_checkpoints()
    assert checkpoints[mailbox] == checkpoint


async def test_record_success_resets_failure_streak(db_session):
    repo = MailboxPollStateRepository(db_session)
    mailbox = _mailbox()

    await repo.record_failure(mailbox_address=mailbox, error_summary="boom")
    await repo.record_failure(mailbox_address=mailbox, error_summary="boom again")
    mid_state = await repo.get(mailbox_address=mailbox)
    assert mid_state.consecutive_failures == 2

    await repo.record_success(
        mailbox_address=mailbox, checkpoint_at=datetime.now(timezone.utc)
    )

    state = await repo.get(mailbox_address=mailbox)
    assert state.consecutive_failures == 0
    assert state.last_failure_at is None
    assert state.last_failure_summary is None


async def test_record_failure_increments_and_returns_streak(db_session):
    repo = MailboxPollStateRepository(db_session)
    mailbox = _mailbox()

    first = await repo.record_failure(mailbox_address=mailbox, error_summary="e1")
    second = await repo.record_failure(mailbox_address=mailbox, error_summary="e2")
    third = await repo.record_failure(mailbox_address=mailbox, error_summary="e3")

    assert (first, second, third) == (1, 2, 3)

    state = await repo.get(mailbox_address=mailbox)
    assert state.consecutive_failures == 3
    assert state.last_failure_summary == "e3"


async def test_mark_alerted_sets_timestamp(db_session):
    repo = MailboxPollStateRepository(db_session)
    mailbox = _mailbox()

    await repo.record_failure(mailbox_address=mailbox, error_summary="boom")
    state_before = await repo.get(mailbox_address=mailbox)
    assert state_before.last_alerted_at is None

    await repo.mark_alerted(mailbox_address=mailbox)

    state_after = await repo.get(mailbox_address=mailbox)
    assert state_after.last_alerted_at is not None


async def test_get_all_checkpoints_excludes_mailboxes_with_no_checkpoint_yet(db_session):
    repo = MailboxPollStateRepository(db_session)
    mailbox = _mailbox()

    # A mailbox that has only ever failed (never a successful fetch)
    # has no checkpoint_at at all — must not appear in
    # get_all_checkpoints (the poller's own fallback to
    # INITIAL_LOOKBACK_MINUTES only makes sense for exactly this case).
    await repo.record_failure(mailbox_address=mailbox, error_summary="boom")

    checkpoints = await repo.get_all_checkpoints()
    assert mailbox not in checkpoints


async def test_get_returns_none_for_unknown_mailbox(db_session):
    repo = MailboxPollStateRepository(db_session)
    assert await repo.get(mailbox_address=_mailbox()) is None

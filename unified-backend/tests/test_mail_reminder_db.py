# test_mail_reminder_db.py
#
# Real-PostgreSQL coverage for the reminder repository / sweep: the
# partial unique index, user isolation, the notification+FIRED atomic
# transition, FOR UPDATE SKIP LOCKED claiming across two sessions, and
# rollback-on-failure.
#
# Same convention as test_notification_clear_all.py: runs against the
# configured (dev) database, uses real seeded users/interactions, and
# rolls back — run this file in isolation (pre-existing pytest-asyncio
# event-loop issue). The whole module SKIPS until the mail_reminders
# migration has been applied to that database.
#
# Safety rules for a shared database:
#   * the sweep entry point that COMMITS (run_due_reminders_sweep) is only
#     ever called with a notifier that always fails, so it can never
#     fire a real user's reminder;
#   * everything else runs inside a transaction that is rolled back;
#   * the one test that must commit (cross-session locking) cleans up
#     its own row in a finally block.

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from shared_models.models import User

from app.database.session import AsyncSessionLocal, engine
from app.notifications.models import Notification
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.mail_reminder import MailReminder, MailReminderStatus
from app.ticketing.repositories.mail_reminder_repository import (
    ActiveReminderExists,
    MailReminderRepository,
)
from app.ticketing.services import mail_reminder_service as svc

NOW = datetime.now(timezone.utc)
# Older than anything real, so "claim the oldest due reminder" is ours.
LONG_AGO = datetime(2000, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        exists = (
            await session.execute(text("select to_regclass('public.mail_reminders')"))
        ).scalar()
        if exists is not None:
            try:
                yield session
            finally:
                await session.rollback()
            await engine.dispose()
            return
    # Table missing: release pooled connections BEFORE skipping so the
    # skip doesn't leave sockets bound to a loop that is about to close.
    await engine.dispose()
    pytest.skip("mail_reminders migration has not been applied to this database.")


async def _two_users(session) -> tuple[uuid.UUID, uuid.UUID]:
    ids = (
        (await session.execute(select(User.user_id).where(User.is_active.is_(True)).limit(2)))
        .scalars()
        .all()
    )
    if len(ids) < 2:
        pytest.skip("Need at least two active seeded users.")
    return ids[0], ids[1]


async def _root_interaction(session) -> Interaction:
    row = (
        await session.execute(
            select(Interaction)
            .where(Interaction.parent_interaction_id.is_(None), Interaction.is_visible.is_(True))
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        pytest.skip("Need at least one visible thread-root interaction.")
    return row


def _reminder(user_id, interaction_id, remind_at=None, status="ACTIVE"):
    return MailReminder(
        user_id=user_id,
        interaction_id=interaction_id,
        remind_at=remind_at or NOW + timedelta(hours=1),
        status=status,
        snooze_count=0,
    )


# ---------------------------------------------------- constraints / indexes


async def test_one_active_reminder_per_user_and_thread(db_session):  # R-013
    a, _ = await _two_users(db_session)
    i = await _root_interaction(db_session)
    repo = MailReminderRepository(db_session)

    await repo.add(_reminder(a, i.interaction_id))
    with pytest.raises(ActiveReminderExists):
        await repo.add(_reminder(a, i.interaction_id))

    # the failed insert did not poison the surrounding transaction
    assert (await repo.list_for_user(a, status="ACTIVE"))


async def test_closed_reminders_do_not_block_a_new_active_one(db_session):
    a, _ = await _two_users(db_session)
    i = await _root_interaction(db_session)
    repo = MailReminderRepository(db_session)
    # Baseline-relative: the user/thread may already have reminders.
    before = len(await repo.list_for_user(a, interaction_id=i.interaction_id))

    for status in ("FIRED", "DISMISSED", "CANCELED"):
        await repo.add(_reminder(a, i.interaction_id, status=status))
    await repo.add(_reminder(a, i.interaction_id))  # ACTIVE still allowed

    assert len(await repo.list_for_user(a, interaction_id=i.interaction_id)) == before + 4


async def test_different_users_may_remind_on_the_same_thread(db_session):  # R-014
    a, b = await _two_users(db_session)
    i = await _root_interaction(db_session)
    repo = MailReminderRepository(db_session)

    await repo.add(_reminder(a, i.interaction_id))
    await repo.add(_reminder(b, i.interaction_id))


async def test_reminders_are_isolated_per_user(db_session):  # R-021 R-003
    a, b = await _two_users(db_session)
    i = await _root_interaction(db_session)
    repo = MailReminderRepository(db_session)
    mine = await repo.add(_reminder(a, i.interaction_id))

    assert await repo.get_for_user(mine.reminder_id, a) is not None
    assert await repo.get_for_user(mine.reminder_id, b) is None
    assert all(r.user_id == a for r in await repo.list_for_user(a))
    assert mine.reminder_id not in {r.reminder_id for r in await repo.list_for_user(b)}


async def test_utc_instant_round_trips(db_session):  # R-008
    a, _ = await _two_users(db_session)
    i = await _root_interaction(db_session)
    repo = MailReminderRepository(db_session)
    when = datetime(2031, 3, 4, 3, 30, tzinfo=timezone.utc)
    r = await repo.add(_reminder(a, i.interaction_id, remind_at=when))
    await db_session.refresh(r)

    assert r.remind_at == when
    assert r.remind_at.utcoffset() == timedelta(0)
    assert r.snooze_count == 0 and r.created_at is not None and r.updated_at is not None


# ------------------------------------------------------- processing


async def test_due_reminder_creates_one_notification_and_fires(db_session):  # R-005 R-033
    a, _ = await _two_users(db_session)
    i = await _root_interaction(db_session)
    repo = MailReminderRepository(db_session)
    notified_before = (
        await db_session.execute(
            select(Notification).where(
                Notification.user_id == a,
                Notification.notification_type == "MAIL_REMINDER_DUE",
                Notification.related_entity_id == i.interaction_id,
            )
        )
    ).scalars().all()
    r = await repo.add(_reminder(a, i.interaction_id, remind_at=LONG_AGO))

    handled = await svc.process_one_due_reminder(db_session, NOW)

    assert handled == r.reminder_id
    assert r.status == MailReminderStatus.FIRED and r.fired_at == NOW
    rows = (
        (
            await db_session.execute(
                select(Notification).where(
                    Notification.user_id == a,
                    Notification.notification_type == "MAIL_REMINDER_DUE",
                    Notification.related_entity_id == i.interaction_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == len(notified_before) + 1  # exactly ONE new notification
    n = next(x for x in rows if x.notification_id not in {b.notification_id for b in notified_before})
    assert n.title == "Mail Reminder"
    assert n.link == f"/inbox?interaction_id={i.interaction_id}"
    assert n.related_entity_type == "interaction"
    assert n.is_read is False
    assert "was due earlier" in n.message  # overdue wording (LONG_AGO)


async def test_second_pass_in_same_transaction_finds_nothing_more(db_session):  # R-024
    a, _ = await _two_users(db_session)
    i = await _root_interaction(db_session)
    await MailReminderRepository(db_session).add(
        _reminder(a, i.interaction_id, remind_at=LONG_AGO)
    )

    first = await svc.process_one_due_reminder(db_session, NOW)
    second = await svc.process_one_due_reminder(db_session, NOW)

    assert first is not None and second is None


async def test_canceled_and_future_reminders_are_not_claimed(db_session):  # R-030
    a, _ = await _two_users(db_session)
    i = await _root_interaction(db_session)
    repo = MailReminderRepository(db_session)
    await repo.add(_reminder(a, i.interaction_id, remind_at=LONG_AGO, status="CANCELED"))
    future = await repo.add(_reminder(a, i.interaction_id, remind_at=NOW + timedelta(days=1)))

    claimed = await repo.claim_next_due(NOW)

    assert claimed is None or claimed.reminder_id != future.reminder_id
    assert future.status == MailReminderStatus.ACTIVE


async def test_snoozed_reminder_is_not_due_until_new_time(db_session):  # R-031
    a, _ = await _two_users(db_session)
    i = await _root_interaction(db_session)
    repo = MailReminderRepository(db_session)
    r = await repo.add(_reminder(a, i.interaction_id, remind_at=LONG_AGO, status="FIRED"))
    r.status, r.remind_at, r.snooze_count = "ACTIVE", NOW + timedelta(hours=1), 1
    await repo.save(r)

    claimed = await repo.claim_next_due(NOW)
    assert claimed is None or claimed.reminder_id != r.reminder_id

    later = await repo.claim_next_due(NOW + timedelta(hours=2))
    assert later is not None and later.reminder_id == r.reminder_id


async def test_hidden_interaction_is_closed_without_notification(db_session):  # R-028
    a, _ = await _two_users(db_session)
    i = await _root_interaction(db_session)
    repo = MailReminderRepository(db_session)
    r = await repo.add(_reminder(a, i.interaction_id, remind_at=LONG_AGO))
    original = i.is_visible
    i.is_visible = False
    await db_session.flush()
    try:
        before = (
            await db_session.execute(
                select(Notification).where(Notification.notification_type == "MAIL_REMINDER_DUE")
            )
        ).scalars().all()

        await svc.process_one_due_reminder(db_session, NOW)

        after = (
            await db_session.execute(
                select(Notification).where(Notification.notification_type == "MAIL_REMINDER_DUE")
            )
        ).scalars().all()
        assert r.status == MailReminderStatus.CANCELED
        assert len(after) == len(before)
    finally:
        i.is_visible = original  # transaction is rolled back anyway


# ---------------------------------------- concurrency / failure (committed)


async def test_skip_locked_second_session_cannot_claim_a_locked_reminder(db_session):  # R-025
    a, _ = await _two_users(db_session)
    i = await _root_interaction(db_session)
    reminder = await MailReminderRepository(db_session).add(
        _reminder(a, i.interaction_id, remind_at=LONG_AGO)
    )
    reminder_id = reminder.reminder_id
    await db_session.commit()  # visible to the other sessions below

    try:
        async with AsyncSessionLocal() as s1, AsyncSessionLocal() as s2:
            claimed_1 = await MailReminderRepository(s1).claim_next_due(NOW)
            assert claimed_1 is not None and claimed_1.reminder_id == reminder_id

            # s1 still holds the row lock (uncommitted): s2 must SKIP it
            # rather than block or return the same row.
            claimed_2 = await MailReminderRepository(s2).claim_next_due(NOW)
            assert claimed_2 is None or claimed_2.reminder_id != reminder_id

            await s1.rollback()  # release the lock without firing

            # now it is claimable again
            claimed_3 = await MailReminderRepository(s2).claim_next_due(NOW)
            assert claimed_3 is not None and claimed_3.reminder_id == reminder_id
            await s2.rollback()
    finally:
        async with AsyncSessionLocal() as cleanup:
            await cleanup.execute(
                text("delete from mail_reminders where reminder_id = :id"),
                {"id": reminder_id},
            )
            await cleanup.commit()


async def test_notification_failure_leaves_reminder_active_in_the_database(db_session):  # R-026
    a, _ = await _two_users(db_session)
    i = await _root_interaction(db_session)
    reminder = await MailReminderRepository(db_session).add(
        _reminder(a, i.interaction_id, remind_at=LONG_AGO)
    )
    reminder_id = reminder.reminder_id
    await db_session.commit()

    class FailingNotifier:
        async def notify(self, *args, **kwargs):
            raise RuntimeError("notification insert failed")

    try:
        # A notifier that ALWAYS fails: nothing real can be fired by this.
        handled = await svc.run_due_reminders_sweep(
            AsyncSessionLocal, NOW, notification_service_factory=lambda db: FailingNotifier()
        )
        assert handled == 0

        async with AsyncSessionLocal() as check:
            row = await MailReminderRepository(check).get_for_user(reminder_id, a)
            assert row.status == MailReminderStatus.ACTIVE and row.fired_at is None
    finally:
        async with AsyncSessionLocal() as cleanup:
            await cleanup.execute(
                text("delete from mail_reminders where reminder_id = :id"),
                {"id": reminder_id},
            )
            await cleanup.commit()

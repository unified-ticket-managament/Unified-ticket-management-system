# test_notification_clear_all.py
#
# Coverage for the persistent "Clear All" fix: the notification bell's
# Clear All button used to be a purely client-side, session-scoped hide
# (a ref in top-navbar.tsx) with no backend concept of "cleared" at all
# — a page refresh, new tab, or different device resurrected the
# "cleared" notifications, still unread, since nothing was ever
# persisted server-side. `Notification.dismissed_at` (soft delete,
# mirroring user_permission_overrides.revoked_at — never a hard
# delete) plus `NotificationRepository.dismiss_all` and the new
# `POST /notifications/clear-all` route close that gap.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_internal_note_recipients.py. Per that file's own note (and the
# root CLAUDE.md's "parallel-track integration pass" section), run this
# file in isolation rather than alongside other DB-touching test files
# in the same pytest process (a pre-existing pytest-asyncio event-loop
# issue, not introduced here).
#
# notifications.user_id is a real users.user_id, so every test below
# uses real seeded active users, never a bare uuid4() (which would
# 500 on insert with ForeignKeyViolationError). The dev database
# already has other, unrelated notifications for these users, so
# every assertion compares against a captured baseline count rather
# than an absolute number.

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from shared_models.models import User

from app.database.session import AsyncSessionLocal, engine
from app.notifications.models import Notification
from app.notifications.repository import NotificationRepository


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_two_active_user_ids(session) -> tuple[uuid.UUID, uuid.UUID]:
    result = await session.execute(
        select(User.user_id).where(User.is_active.is_(True)).limit(2)
    )
    user_ids = result.scalars().all()
    if len(user_ids) < 2:
        pytest.skip("Need at least two active seeded users.")
    return user_ids[0], user_ids[1]


async def _make_notification(session, *, user_id, is_read=False) -> Notification:
    notification = Notification(
        notification_id=uuid.uuid4(),
        user_id=user_id,
        notification_type="TICKET_ASSIGNED",
        title="Test notification",
        message="Test message",
        link="/tickets/00000000-0000-0000-0000-000000000000",
        related_entity_type="ticket",
        related_entity_id=uuid.uuid4(),
        is_read=is_read,
        created_at=datetime.now(timezone.utc),
    )
    session.add(notification)
    await session.flush()
    return notification


async def test_dismiss_all_excludes_rows_from_list_and_count(db_session):
    user_id, _ = await _get_two_active_user_ids(db_session)
    repository = NotificationRepository(db_session)

    baseline = await repository.count_for_user(user_id)

    await _make_notification(db_session, user_id=user_id)
    await _make_notification(db_session, user_id=user_id)

    assert await repository.count_for_user(user_id) == baseline + 2

    await repository.dismiss_all(user_id)

    assert await repository.count_for_user(user_id) == baseline
    assert await repository.count_for_user(user_id, unread_only=True) == 0


async def test_dismiss_all_never_touches_another_users_notifications(db_session):
    user_a, user_b = await _get_two_active_user_ids(db_session)
    repository = NotificationRepository(db_session)

    baseline_a = await repository.count_for_user(user_a)
    baseline_b = await repository.count_for_user(user_b)

    await _make_notification(db_session, user_id=user_a)
    await _make_notification(db_session, user_id=user_b)

    await repository.dismiss_all(user_a)

    assert await repository.count_for_user(user_a) == baseline_a
    assert await repository.count_for_user(user_b) == baseline_b + 1


async def test_dismiss_all_does_not_change_is_read_state(db_session):
    user_id, _ = await _get_two_active_user_ids(db_session)
    repository = NotificationRepository(db_session)

    unread = await _make_notification(db_session, user_id=user_id, is_read=False)
    read = await _make_notification(db_session, user_id=user_id, is_read=True)

    await repository.dismiss_all(user_id)

    result = await db_session.execute(
        select(Notification).where(
            Notification.notification_id.in_(
                [unread.notification_id, read.notification_id]
            )
        )
    )
    rows = {row.notification_id: row for row in result.scalars().all()}

    assert rows[unread.notification_id].is_read is False
    assert rows[read.notification_id].is_read is True
    # Both must also have been dismissed by the call above.
    assert rows[unread.notification_id].dismissed_at is not None
    assert rows[read.notification_id].dismissed_at is not None


async def test_dismiss_all_is_a_soft_delete_not_a_hard_delete(db_session):
    user_id, _ = await _get_two_active_user_ids(db_session)
    repository = NotificationRepository(db_session)

    notification = await _make_notification(db_session, user_id=user_id)

    await repository.dismiss_all(user_id)

    # Bypassing the repository's own dismissed_at filter to prove the
    # row still physically exists — dismissal must never hard-delete.
    result = await db_session.execute(
        select(Notification).where(
            Notification.notification_id == notification.notification_id
        )
    )
    row = result.scalar_one()
    assert row.dismissed_at is not None


async def test_dismiss_all_is_idempotent(db_session):
    user_id, _ = await _get_two_active_user_ids(db_session)
    repository = NotificationRepository(db_session)

    notification = await _make_notification(db_session, user_id=user_id)

    await repository.dismiss_all(user_id)
    await repository.dismiss_all(user_id)  # calling it again must not error

    result = await db_session.execute(
        select(Notification).where(
            Notification.notification_id == notification.notification_id
        )
    )
    assert result.scalar_one().dismissed_at is not None

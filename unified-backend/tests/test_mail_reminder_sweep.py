# test_mail_reminder_sweep.py
#
# Unit coverage for the due-reminder sweep (mail_reminder_service.
# run_due_reminders_sweep / process_one_due_reminder) on fakes that model
# the three database semantics the design depends on:
#
#   * a claim takes a row lock held until commit/rollback, and a second
#     claimer SKIPS locked rows (FOR UPDATE SKIP LOCKED)
#   * commit publishes the session's notification rows and state changes
#   * rollback discards both together (so a failed notify leaves the
#     reminder ACTIVE and creates no notification)
#
# The real Postgres behaviour of the same properties is exercised in
# test_mail_reminder_db.py (skipped until the mail_reminders migration
# has been applied to the target database).

import asyncio
import copy
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app.ticketing.models  # noqa: F401
from app.notifications.service import NotificationType
from app.ticketing.models.mail_reminder import MailReminder, MailReminderStatus
from app.ticketing.services import mail_reminder_service as svc

NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reminders: dict[uuid.UUID, MailReminder] = {}
        self.interactions: dict[uuid.UUID, SimpleNamespace] = {}
        self.users: dict[uuid.UUID, SimpleNamespace] = {}
        self.notifications: list[dict] = []
        self.locked: set[uuid.UUID] = set()
        self.fail_notify_for: set[uuid.UUID] = set()

    def add_reminder(self, *, remind_at, user=None, interaction=None, status="ACTIVE"):
        user = user or self.add_user()
        interaction = interaction or self.add_interaction()
        r = MailReminder(
            reminder_id=uuid.uuid4(),
            user_id=user.user_id,
            interaction_id=interaction.interaction_id,
            remind_at=remind_at,
            status=status,
            snooze_count=0,
        )
        self.reminders[r.reminder_id] = r
        return r

    def add_user(self, active=True):
        u = SimpleNamespace(user_id=uuid.uuid4(), is_active=active)
        self.users[u.user_id] = u
        return u

    def add_interaction(self, *, visible=True, subject="Invoice 42"):
        i = SimpleNamespace(
            interaction_id=uuid.uuid4(), is_visible=visible, subject=subject
        )
        self.interactions[i.interaction_id] = i
        return i


class FakeSession:
    def __init__(self, store: Store):
        self.store = store
        self.snapshots: dict[uuid.UUID, dict] = {}
        self.locks: set[uuid.UUID] = set()
        self.pending_notifications: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self._release()

    def _release(self):
        self.store.locked -= self.locks
        self.locks.clear()

    async def flush(self):
        pass

    async def commit(self):
        self.store.notifications.extend(self.pending_notifications)
        self.pending_notifications.clear()
        self.snapshots.clear()
        self._release()

    async def rollback(self):
        for rid, snap in self.snapshots.items():
            r = self.store.reminders[rid]
            for k, v in snap.items():
                setattr(r, k, v)
        self.snapshots.clear()
        self.pending_notifications.clear()
        self._release()


def install_fakes(monkeypatch, store: Store):
    class FakeReminderRepo:
        def __init__(self, db):
            self.db = db

        async def claim_next_due(self, now, *, exclude_ids=None):
            await asyncio.sleep(0)  # let a concurrent tick interleave
            candidates = sorted(
                (
                    r
                    for r in store.reminders.values()
                    if r.status == MailReminderStatus.ACTIVE
                    and r.remind_at <= now
                    and r.reminder_id not in store.locked
                    and r.reminder_id not in (exclude_ids or set())
                ),
                key=lambda r: r.remind_at,
            )
            if not candidates:
                return None
            r = candidates[0]
            store.locked.add(r.reminder_id)
            self.db.locks.add(r.reminder_id)
            self.db.snapshots[r.reminder_id] = {
                "status": r.status,
                "fired_at": r.fired_at,
                "completed_at": r.completed_at,
            }
            return r

    class FakeInteractionRepo:
        def __init__(self, db):
            pass

        async def get_by_id(self, interaction_id):
            return store.interactions.get(interaction_id)

    class FakeUserRepo:
        def __init__(self, db):
            pass

        async def get_by_id(self, user_id):
            return store.users.get(user_id)

    monkeypatch.setattr(svc, "MailReminderRepository", FakeReminderRepo)
    monkeypatch.setattr(svc, "InteractionRepository", FakeInteractionRepo)
    monkeypatch.setattr(svc, "UserRepository", FakeUserRepo)


class FakeNotificationService:
    """Records into the session's *pending* rows, like a flushed INSERT."""

    def __init__(self, db: FakeSession, store: Store):
        self.db = db
        self.store = store

    async def notify(self, user_ids, notification_type, title, message, **kw):
        await asyncio.sleep(0)
        related = kw.get("related_entity_id")
        if related in self.store.fail_notify_for:
            raise RuntimeError("notification insert failed")
        self.db.pending_notifications.append(
            {
                "user_ids": user_ids,
                "type": notification_type,
                "title": title,
                "message": message,
                **kw,
            }
        )


@pytest.fixture
def store(monkeypatch):
    s = Store()
    install_fakes(monkeypatch, s)
    return s


def factory_for(store):
    return lambda: FakeSession(store)


def notifier_for(store):
    return lambda db: FakeNotificationService(db, store)


async def sweep(store, now=NOW):
    return await svc.run_due_reminders_sweep(
        factory_for(store), now, notification_service_factory=notifier_for(store)
    )


# --------------------------------------------------------------------------


async def test_due_reminder_fires_once_with_expected_notification(store):  # R-005 R-033
    interaction = store.add_interaction(subject="Contract renewal")
    user = store.add_user()
    r = store.add_reminder(
        remind_at=NOW - timedelta(minutes=1), user=user, interaction=interaction
    )

    assert await sweep(store) == 1

    assert r.status == MailReminderStatus.FIRED
    assert r.fired_at == NOW
    assert len(store.notifications) == 1
    n = store.notifications[0]
    assert n["user_ids"] == user.user_id
    assert n["type"] == NotificationType.MAIL_REMINDER_DUE == "MAIL_REMINDER_DUE"
    assert n["title"] == "Mail Reminder"
    assert n["message"] == "Reminder: Contract renewal"
    assert n["link"] == f"/inbox?interaction_id={interaction.interaction_id}"
    assert n["related_entity_type"] == "interaction"
    assert n["related_entity_id"] == interaction.interaction_id


async def test_notification_never_includes_email_body(store):
    i = store.add_interaction(subject="Subject only")
    i.body = "SECRET BODY"
    i.payload = {"body": "SECRET BODY"}
    store.add_reminder(remind_at=NOW - timedelta(seconds=5), interaction=i)

    await sweep(store)

    assert "SECRET" not in repr(store.notifications)


async def test_not_yet_due_reminder_is_left_alone(store):
    r = store.add_reminder(remind_at=NOW + timedelta(minutes=1))
    assert await sweep(store) == 0
    assert r.status == MailReminderStatus.ACTIVE
    assert store.notifications == []


async def test_sweep_run_twice_creates_one_notification(store):  # R-024
    store.add_reminder(remind_at=NOW - timedelta(seconds=1))

    assert await sweep(store) == 1
    assert await sweep(store) == 0

    assert len(store.notifications) == 1


async def test_concurrent_sweeps_fire_each_reminder_exactly_once(store):  # R-025
    reminders = [
        store.add_reminder(remind_at=NOW - timedelta(minutes=i + 1)) for i in range(5)
    ]

    results = await asyncio.gather(sweep(store), sweep(store), sweep(store))

    assert sum(results) == 5
    assert len(store.notifications) == 5
    assert {n["related_entity_id"] for n in store.notifications} == {
        r.interaction_id for r in reminders
    }
    assert all(r.status == MailReminderStatus.FIRED for r in reminders)


async def test_notification_failure_keeps_reminder_active_and_retries(store):  # R-026
    r = store.add_reminder(remind_at=NOW - timedelta(seconds=1))
    store.fail_notify_for.add(r.interaction_id)

    assert await sweep(store) == 0

    # rolled back together: still ACTIVE, no notification, lock released
    assert r.status == MailReminderStatus.ACTIVE
    assert r.fired_at is None
    assert store.notifications == []
    assert store.locked == set()

    # next tick (notifier healthy again) fires it exactly once
    store.fail_notify_for.clear()
    assert await sweep(store) == 1
    assert r.status == MailReminderStatus.FIRED
    assert len(store.notifications) == 1


async def test_one_failing_reminder_does_not_block_the_others(store):
    bad = store.add_reminder(remind_at=NOW - timedelta(minutes=10))
    good = store.add_reminder(remind_at=NOW - timedelta(minutes=1))
    store.fail_notify_for.add(bad.interaction_id)

    assert await sweep(store) == 1

    assert good.status == MailReminderStatus.FIRED
    assert bad.status == MailReminderStatus.ACTIVE


async def test_overdue_reminder_fires_after_downtime(store):  # R-027
    r = store.add_reminder(remind_at=NOW - timedelta(days=3))

    assert await sweep(store) == 1

    assert r.status == MailReminderStatus.FIRED
    assert "was due earlier" in store.notifications[0]["message"]


async def test_barely_late_reminder_has_no_overdue_note(store):
    store.add_reminder(remind_at=NOW - timedelta(seconds=30))
    await sweep(store)
    assert "due earlier" not in store.notifications[0]["message"]


@pytest.mark.parametrize("status", ["CANCELED", "DISMISSED", "FIRED"])
async def test_non_active_reminders_never_fire(store, status):  # R-030
    r = store.add_reminder(remind_at=NOW - timedelta(hours=1), status=status)
    assert await sweep(store) == 0
    assert r.status == status
    assert store.notifications == []


async def test_snoozed_reminder_fires_at_new_time_not_old(store):  # R-031
    r = store.add_reminder(remind_at=NOW - timedelta(minutes=1), status="FIRED")
    # snooze: same row, back to ACTIVE, pushed an hour out
    r.status = MailReminderStatus.ACTIVE
    r.remind_at = NOW + timedelta(hours=1)
    r.snooze_count = 1

    assert await sweep(store, NOW) == 0
    assert await sweep(store, NOW + timedelta(minutes=59)) == 0
    assert await sweep(store, NOW + timedelta(hours=1, seconds=1)) == 1
    assert len(store.notifications) == 1


async def test_hidden_email_is_closed_without_notification(store):  # R-028
    i = store.add_interaction(visible=False)
    r = store.add_reminder(remind_at=NOW - timedelta(seconds=1), interaction=i)

    assert await sweep(store) == 1

    assert r.status == MailReminderStatus.CANCELED
    assert r.completed_at == NOW
    assert store.notifications == []


async def test_deleted_interaction_is_closed_without_notification(store):  # R-032
    r = store.add_reminder(remind_at=NOW - timedelta(seconds=1))
    del store.interactions[r.interaction_id]

    assert await sweep(store) == 1

    assert r.status == MailReminderStatus.CANCELED
    assert store.notifications == []


async def test_inactive_user_is_closed_without_notification(store):  # R-029
    r = store.add_reminder(
        remind_at=NOW - timedelta(seconds=1), user=store.add_user(active=False)
    )

    assert await sweep(store) == 1

    assert r.status == MailReminderStatus.CANCELED
    assert store.notifications == []


async def test_only_the_owner_is_notified(store):
    owner = store.add_user()
    other = store.add_user()
    i = store.add_interaction()
    store.add_reminder(remind_at=NOW - timedelta(seconds=1), user=owner, interaction=i)
    store.add_reminder(
        remind_at=NOW + timedelta(hours=1), user=other, interaction=i
    )  # other's reminder isn't due

    await sweep(store)

    assert [n["user_ids"] for n in store.notifications] == [owner.user_id]


async def test_sweep_stops_when_claim_itself_fails(monkeypatch, store):
    class Boom:
        def __init__(self, db):
            pass

        async def claim_next_due(self, *a, **k):
            raise ConnectionError("db unavailable")

    monkeypatch.setattr(svc, "MailReminderRepository", Boom)
    store.add_reminder(remind_at=NOW - timedelta(seconds=1))

    # Must return (not spin forever) and must not raise out of the tick.
    assert await sweep(store) == 0
    assert store.notifications == []


async def test_batch_is_bounded_per_tick(monkeypatch, store):
    monkeypatch.setattr(svc, "MAX_HANDLED_PER_TICK", 3)
    for i in range(5):
        store.add_reminder(remind_at=NOW - timedelta(minutes=i + 1))

    assert await sweep(store) == 3
    assert await sweep(store) == 2  # remainder picked up next tick

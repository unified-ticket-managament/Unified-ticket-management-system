# test_mail_reminder_service.py
#
# Unit coverage for MailReminderService (create / ownership / lifecycle /
# validation) on in-memory fakes — no database. The fakes mirror the real
# repository's contract, including the partial unique index "one ACTIVE
# reminder per (user, thread)" (raised as ActiveReminderExists).
#
# Matrix ids (R-xxx) reference the Mail Reminder test plan.

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.ticketing.models  # noqa: F401  (registers every mapper)
from app.ticketing.models.mail_reminder import MailReminder, MailReminderStatus
from app.ticketing.repositories.mail_reminder_repository import ActiveReminderExists
from app.ticketing.services.mail_reminder_service import (
    MAX_REMINDER_HORIZON,
    MailReminderService,
)

NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


class FakeReminderRepository:
    def __init__(self):
        self.rows: dict[uuid.UUID, MailReminder] = {}

    def _check_unique(self, reminder):
        if reminder.status != MailReminderStatus.ACTIVE:
            return
        for other in self.rows.values():
            if (
                other is not reminder
                and other.status == MailReminderStatus.ACTIVE
                and other.user_id == reminder.user_id
                and other.interaction_id == reminder.interaction_id
            ):
                raise ActiveReminderExists()

    async def add(self, reminder):
        if reminder.reminder_id is None:
            reminder.reminder_id = uuid.uuid4()
        self._check_unique(reminder)
        reminder.created_at = reminder.updated_at = NOW
        self.rows[reminder.reminder_id] = reminder
        return reminder

    async def save(self, reminder):
        self._check_unique(reminder)
        return reminder

    async def get_for_user(self, reminder_id, user_id):
        row = self.rows.get(reminder_id)
        return row if row is not None and row.user_id == user_id else None

    async def list_for_user(self, user_id, *, status=None, interaction_id=None, limit=500):
        return [
            r
            for r in self.rows.values()
            if r.user_id == user_id
            and (status is None or r.status == status)
            and (interaction_id is None or r.interaction_id == interaction_id)
        ]


class FakeInteractionRepository:
    def __init__(self, interactions):
        self.by_id = {i.interaction_id: i for i in interactions}

    async def get_by_id(self, interaction_id):
        return self.by_id.get(interaction_id)

    async def find_thread_root(self, interaction_id):
        node = self.by_id.get(interaction_id)
        while node is not None and node.parent_interaction_id is not None:
            node = self.by_id.get(node.parent_interaction_id)
        return node


def make_interaction(parent=None, *, visible=True, subject="Quarterly report"):
    return SimpleNamespace(
        interaction_id=uuid.uuid4(),
        parent_interaction_id=parent.interaction_id if parent else None,
        is_visible=visible,
        subject=subject,
    )


def make_user():
    return SimpleNamespace(user_id=uuid.uuid4(), is_active=True)


class Env:
    def __init__(self, *, can_view=True):
        self.root = make_interaction()
        self.reply = make_interaction(self.root)
        self.nested_reply = make_interaction(self.reply)
        self.hidden = make_interaction(visible=False)
        self.repo = FakeReminderRepository()
        self.interactions = FakeInteractionRepository(
            [self.root, self.reply, self.nested_reply, self.hidden]
        )
        self.can_view = can_view
        self.checked: list[tuple] = []
        self.service = MailReminderService(
            self.repo, self.interactions, ensure_can_view=self._ensure_can_view
        )

    async def _ensure_can_view(self, interaction_id, user):
        self.checked.append((interaction_id, user.user_id))
        if not self.can_view:
            raise HTTPException(status_code=403, detail="Not allowed")


@pytest.fixture
def env():
    return Env()


@pytest.fixture
def alice():
    return make_user()


@pytest.fixture
def bob():
    return make_user()


def at(**delta):
    return NOW + timedelta(**delta)


# ---------------------------------------------------------------- creation


async def test_create_valid_reminder(env, alice):  # R-001
    r = await env.service.create(alice, env.root.interaction_id, at(hours=2), now=NOW)

    assert r.status == MailReminderStatus.ACTIVE
    assert r.user_id == alice.user_id
    assert r.interaction_id == env.root.interaction_id
    assert r.remind_at == at(hours=2)
    assert r.snooze_count == 0


async def test_create_missing_interaction_is_404(env, alice):  # R-010
    with pytest.raises(HTTPException) as exc:
        await env.service.create(alice, uuid.uuid4(), at(hours=1), now=NOW)
    assert exc.value.status_code == 404


async def test_create_inaccessible_email_is_404_not_403(alice):  # R-011
    env = Env(can_view=False)
    with pytest.raises(HTTPException) as exc:
        await env.service.create(alice, env.root.interaction_id, at(hours=1), now=NOW)
    assert exc.value.status_code == 404
    assert env.repo.rows == {}


async def test_create_checks_access_on_the_thread_root(env, alice):
    await env.service.create(alice, env.nested_reply.interaction_id, at(hours=1), now=NOW)
    assert env.checked == [(env.root.interaction_id, alice.user_id)]


async def test_reply_resolves_to_thread_root(env, alice):  # R-012
    r = await env.service.create(alice, env.reply.interaction_id, at(hours=1), now=NOW)
    assert r.interaction_id == env.root.interaction_id

    # deeper nesting resolves all the way up
    r2 = await env.service.create(
        make_user(), env.nested_reply.interaction_id, at(hours=1), now=NOW
    )
    assert r2.interaction_id == env.root.interaction_id


async def test_hidden_email_is_404(env, alice):  # R-028
    with pytest.raises(HTTPException) as exc:
        await env.service.create(alice, env.hidden.interaction_id, at(hours=1), now=NOW)
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    "delta",
    [timedelta(days=-1), timedelta(seconds=-1), timedelta(0)],
    ids=["past", "just-past", "equal-to-now"],
)
async def test_create_rejects_past_and_current_time(env, alice, delta):  # R-002
    with pytest.raises(HTTPException) as exc:
        await env.service.create(alice, env.root.interaction_id, NOW + delta, now=NOW)
    assert exc.value.status_code == 422


async def test_create_rejects_naive_datetime(env, alice):  # R-007
    naive = datetime(2026, 12, 1, 9, 0, 0)
    with pytest.raises(HTTPException) as exc:
        await env.service.create(alice, env.root.interaction_id, naive, now=NOW)
    assert exc.value.status_code == 422


async def test_create_rejects_beyond_max_horizon(env, alice):  # R-009
    with pytest.raises(HTTPException) as exc:
        await env.service.create(
            alice,
            env.root.interaction_id,
            NOW + MAX_REMINDER_HORIZON + timedelta(minutes=1),
            now=NOW,
        )
    assert exc.value.status_code == 422

    ok = await env.service.create(
        alice, env.root.interaction_id, NOW + MAX_REMINDER_HORIZON, now=NOW
    )
    assert ok.status == MailReminderStatus.ACTIVE


async def test_offset_datetime_is_stored_as_utc_instant(env, alice):  # R-008
    ist = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 10, 8, 9, 0, 0, tzinfo=ist)  # 03:30 UTC

    r = await env.service.create(alice, env.root.interaction_id, local, now=NOW)

    assert r.remind_at == datetime(2026, 10, 8, 3, 30, 0, tzinfo=timezone.utc)
    assert r.remind_at.utcoffset() == timedelta(0)


async def test_duplicate_active_reminder_is_409(env, alice):  # R-013
    await env.service.create(alice, env.root.interaction_id, at(hours=1), now=NOW)
    with pytest.raises(HTTPException) as exc:
        await env.service.create(alice, env.reply.interaction_id, at(hours=2), now=NOW)
    assert exc.value.status_code == 409


async def test_duplicate_allowed_after_previous_closed(env, alice):
    first = await env.service.create(alice, env.root.interaction_id, at(hours=1), now=NOW)
    await env.service.cancel(alice, first.reminder_id, now=NOW)

    second = await env.service.create(alice, env.root.interaction_id, at(hours=2), now=NOW)
    assert second.reminder_id != first.reminder_id


async def test_different_users_can_remind_on_same_email(env, alice, bob):  # R-014
    a = await env.service.create(alice, env.root.interaction_id, at(hours=1), now=NOW)
    b = await env.service.create(bob, env.root.interaction_id, at(hours=1), now=NOW)
    assert a.reminder_id != b.reminder_id


# --------------------------------------------------------------- ownership


async def _made(env, user):
    return await env.service.create(user, env.root.interaction_id, at(hours=3), now=NOW)


@pytest.mark.parametrize(
    "op",
    [
        lambda s, u, rid: s.get(u, rid),
        lambda s, u, rid: s.update(u, rid, at(hours=5), now=NOW),
        lambda s, u, rid: s.cancel(u, rid, now=NOW),
        lambda s, u, rid: s.snooze(u, rid, minutes=60, now=NOW),
        lambda s, u, rid: s.dismiss(u, rid, now=NOW),
    ],
    ids=["get", "patch", "delete", "snooze", "dismiss"],
)
async def test_other_users_reminder_is_404(env, alice, bob, op):  # R-003
    reminder = await _made(env, alice)
    reminder.status = MailReminderStatus.FIRED  # so dismiss/snooze would otherwise succeed

    with pytest.raises(HTTPException) as exc:
        await op(env.service, bob, reminder.reminder_id)

    assert exc.value.status_code == 404
    # ...and it is byte-for-byte what a nonexistent id produces
    with pytest.raises(HTTPException) as missing:
        await op(env.service, bob, uuid.uuid4())
    assert missing.value.detail == exc.value.detail
    assert reminder.status == MailReminderStatus.FIRED  # untouched


async def test_list_returns_only_own_reminders(env, alice, bob):  # R-021
    await _made(env, alice)
    await _made(env, bob)

    mine = await env.service.list_reminders(alice)

    assert len(mine) == 1
    assert all(r.user_id == alice.user_id for r in mine)


async def test_list_filters_by_status_and_interaction(env, alice):
    r = await _made(env, alice)
    await env.service.cancel(alice, r.reminder_id, now=NOW)
    await _made(env, alice)

    active = await env.service.list_reminders(alice, status_filter="ACTIVE")
    canceled = await env.service.list_reminders(alice, status_filter="CANCELED")
    other = await env.service.list_reminders(alice, interaction_id=uuid.uuid4())

    assert len(active) == 1 and len(canceled) == 1 and other == []


async def test_list_rejects_unknown_status(env, alice):
    with pytest.raises(HTTPException) as exc:
        await env.service.list_reminders(alice, status_filter="BOGUS")
    assert exc.value.status_code == 422


# ---------------------------------------------------------------- lifecycle


async def test_edit_active_reminder(env, alice):  # R-015
    r = await _made(env, alice)
    updated = await env.service.update(alice, r.reminder_id, at(days=2), now=NOW)
    assert updated.remind_at == at(days=2)
    assert updated.status == MailReminderStatus.ACTIVE


@pytest.mark.parametrize(
    "status",
    [MailReminderStatus.FIRED, MailReminderStatus.CANCELED, MailReminderStatus.DISMISSED],
)
async def test_only_active_reminder_can_be_edited(env, alice, status):  # R-016
    r = await _made(env, alice)
    r.status = status
    with pytest.raises(HTTPException) as exc:
        await env.service.update(alice, r.reminder_id, at(days=2), now=NOW)
    assert exc.value.status_code == 409


async def test_edit_validates_the_new_time(env, alice):
    r = await _made(env, alice)
    with pytest.raises(HTTPException) as exc:
        await env.service.update(alice, r.reminder_id, at(hours=-1), now=NOW)
    assert exc.value.status_code == 422


async def test_cancel_sets_canceled_and_completed_at(env, alice):  # R-017
    r = await _made(env, alice)
    out = await env.service.cancel(alice, r.reminder_id, now=NOW)
    assert out.status == MailReminderStatus.CANCELED
    assert out.completed_at == NOW


async def test_cancel_twice_is_409(env, alice):
    r = await _made(env, alice)
    await env.service.cancel(alice, r.reminder_id, now=NOW)
    with pytest.raises(HTTPException) as exc:
        await env.service.cancel(alice, r.reminder_id, now=NOW)
    assert exc.value.status_code == 409


async def test_fired_reminder_can_be_dismissed(env, alice):  # R-020
    r = await _made(env, alice)
    r.status = MailReminderStatus.FIRED
    r.fired_at = NOW

    out = await env.service.dismiss(alice, r.reminder_id, now=NOW)

    assert out.status == MailReminderStatus.DISMISSED
    assert out.completed_at == NOW


@pytest.mark.parametrize(
    "status", [MailReminderStatus.ACTIVE, MailReminderStatus.CANCELED, MailReminderStatus.DISMISSED]
)
async def test_only_fired_reminder_can_be_dismissed(env, alice, status):
    r = await _made(env, alice)
    r.status = status
    with pytest.raises(HTTPException) as exc:
        await env.service.dismiss(alice, r.reminder_id, now=NOW)
    assert exc.value.status_code == 409


async def test_snooze_fired_reminder_reuses_row(env, alice):  # R-018
    r = await _made(env, alice)
    r.status = MailReminderStatus.FIRED
    r.fired_at = at(hours=-1)

    out = await env.service.snooze(alice, r.reminder_id, minutes=60, now=NOW)

    assert out is r
    assert out.status == MailReminderStatus.ACTIVE
    assert out.remind_at == NOW + timedelta(hours=1)
    assert out.snooze_count == 1
    assert out.fired_at is None
    assert len(env.repo.rows) == 1


async def test_snooze_absolute_time_and_counts_repeats(env, alice):
    r = await _made(env, alice)
    await env.service.snooze(alice, r.reminder_id, remind_at=at(days=1), now=NOW)
    out = await env.service.snooze(alice, r.reminder_id, minutes=15, now=NOW)
    assert out.snooze_count == 2
    assert out.remind_at == NOW + timedelta(minutes=15)


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"minutes": 5, "remind_at": at(hours=1)}],
    ids=["neither", "both"],
)
async def test_snooze_needs_exactly_one_target(env, alice, kwargs):  # R-019
    r = await _made(env, alice)
    with pytest.raises(HTTPException) as exc:
        await env.service.snooze(alice, r.reminder_id, now=NOW, **kwargs)
    assert exc.value.status_code == 422


async def test_snooze_to_past_is_422(env, alice):  # R-019
    r = await _made(env, alice)
    with pytest.raises(HTTPException) as exc:
        await env.service.snooze(alice, r.reminder_id, remind_at=at(hours=-2), now=NOW)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("status", [MailReminderStatus.CANCELED, MailReminderStatus.DISMISSED])
async def test_closed_reminder_cannot_be_snoozed(env, alice, status):  # R-019
    r = await _made(env, alice)
    r.status = status
    with pytest.raises(HTTPException) as exc:
        await env.service.snooze(alice, r.reminder_id, minutes=5, now=NOW)
    assert exc.value.status_code == 409


async def test_snooze_conflicting_with_a_newer_active_reminder_is_409(env, alice):
    old = await _made(env, alice)
    old.status = MailReminderStatus.FIRED
    await _made(env, alice)  # a fresh ACTIVE one was created after it fired

    with pytest.raises(HTTPException) as exc:
        await env.service.snooze(alice, old.reminder_id, minutes=5, now=NOW)
    assert exc.value.status_code == 409

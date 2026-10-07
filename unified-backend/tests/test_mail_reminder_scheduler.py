# test_mail_reminder_scheduler.py
#
# Scheduler lifecycle (R-052), the local-development safety flag, and the
# guarantee that adding MAIL_REMINDER_DUE leaves the existing notification
# types and email policy untouched (R-034).

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from app.core import mail_reminder_scheduler as sched
from app.notifications.email_policy import EMAIL_ELIGIBLE_NOTIFICATION_TYPES
from app.notifications.service import NotificationType


def settings(app_env="development", enabled=None, interval=30):
    return SimpleNamespace(
        app_env=app_env,
        mail_reminder_scheduler_enabled=enabled,
        mail_reminder_sweep_interval_seconds=interval,
    )


@pytest.mark.parametrize(
    "app_env, enabled, expected",
    [
        ("production", None, True),
        ("Production", None, True),
        ("prod", None, True),
        ("development", None, False),  # local dev defaults OFF
        ("", None, False),
        ("development", True, True),  # explicit override on
        ("production", False, False),  # explicit override off
    ],
)
def test_enabled_flag_resolution(monkeypatch, app_env, enabled, expected):
    monkeypatch.setattr(sched, "get_settings", lambda: settings(app_env, enabled))
    assert sched.is_enabled() is expected


@pytest.fixture
def fresh_scheduler(monkeypatch):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    s = AsyncIOScheduler()
    monkeypatch.setattr(sched, "scheduler", s)
    yield s
    try:
        if s.running:
            s.shutdown(wait=False)
    except RuntimeError:
        pass  # the test's event loop is already closed; nothing left to stop


async def test_start_registers_one_job_and_is_idempotent(monkeypatch, fresh_scheduler):
    monkeypatch.setattr(
        sched, "get_settings", lambda: settings("production", interval=45)
    )

    try:
        sched.start_scheduler()
        sched.start_scheduler()  # second call must be a no-op

        jobs = fresh_scheduler.get_jobs()
        assert fresh_scheduler.running
        assert [j.id for j in jobs] == [sched.MAIL_REMINDER_JOB_ID]
        assert jobs[0].max_instances == 1
        assert jobs[0].trigger.interval.total_seconds() == 45
    finally:
        sched.shutdown_scheduler()


async def test_disabled_process_never_starts_a_scheduler(monkeypatch, fresh_scheduler):
    monkeypatch.setattr(sched, "get_settings", lambda: settings("development"))

    sched.start_scheduler()

    assert not fresh_scheduler.running
    assert fresh_scheduler.get_jobs() == []


async def test_shutdown_stops_the_scheduler_and_is_safe_when_not_running(
    monkeypatch, fresh_scheduler
):
    monkeypatch.setattr(sched, "get_settings", lambda: settings("production"))
    sched.shutdown_scheduler()  # not running: must not raise

    sched.start_scheduler()
    sched.shutdown_scheduler()
    await asyncio.sleep(0)

    assert not fresh_scheduler.running


async def test_tick_swallows_errors(monkeypatch):
    async def boom(_factory):
        raise RuntimeError("db down")

    monkeypatch.setattr(sched, "run_due_reminders_sweep", boom)
    await sched._run_sweep()  # must not raise (a raised error would kill the job)


def test_app_lifespan_wires_the_scheduler():
    import app.main as main

    src = inspect.getsource(main.lifespan)
    assert "start_mail_reminder_scheduler()" in src
    assert "shutdown_mail_reminder_scheduler()" in src
    # existing schedulers are still started/stopped
    for name in (
        "start_scheduler()",
        "start_graph_subscription_scheduler()",
        "start_graph_mail_poll_scheduler()",
        "start_draft_retention_scheduler()",
        "start_rule_run_scheduler()",
        "shutdown_rule_run_scheduler()",
        "shutdown_scheduler()",
    ):
        assert name in src


def test_router_exposes_the_expected_routes():
    import app.main as main
    from app.ticketing.api.mail_reminder import router

    paths = {(tuple(sorted(r.methods)), r.path) for r in router.routes}
    assert (("POST",), "/mail-reminders") in paths
    assert (("GET",), "/mail-reminders") in paths
    assert (("GET",), "/mail-reminders/{reminder_id}") in paths
    assert (("PATCH",), "/mail-reminders/{reminder_id}") in paths
    assert (("DELETE",), "/mail-reminders/{reminder_id}") in paths
    assert (("POST",), "/mail-reminders/{reminder_id}/snooze") in paths
    assert (("POST",), "/mail-reminders/{reminder_id}/dismiss") in paths
    assert "ticketing_mail_reminder_router" in open(main.__file__, encoding="utf8").read()


# ------------------------------------------------- existing notifications


EXISTING_TYPES = {
    "MAIL_RECEIVED", "CLIENT_REPLY", "MAIL_FORWARDED", "OTP_FORWARDED",
    "MAIL_RULE_FORWARDED", "MAIL_BOUNCE_DETECTED", "UNMATCHED_INBOX_EMAIL",
    "TICKET_ASSIGNED", "TICKET_STATUS_CHANGED", "TICKET_PRIORITY_CHANGED",
    "TICKET_RESOLVED", "INTERNAL_NOTE_ADDED", "PERMISSION_REQUESTED",
    "PERMISSION_APPROVED", "PERMISSION_REJECTED", "PERMISSION_REVOKED",
    "PERMISSION_GRANTED", "SLA_HALF_ELAPSED", "SLA_AT_RISK", "SLA_BREACHED",
    "SLA_ESCALATED", "ESCALATION_CREATED", "ESCALATION_ACKNOWLEDGED",
    "ESCALATION_ADVANCED", "ESCALATION_CLOSED", "GRAPH_SUBSCRIPTION_FAILED",
    "MAILBOX_POLL_STALLED",
}


def test_existing_notification_types_unchanged_and_new_one_is_distinct():  # R-034
    values = {
        k: v
        for k, v in vars(NotificationType).items()
        if k.isupper() and isinstance(v, str)
    }
    for name in EXISTING_TYPES:
        assert values[name] == name
    assert values["MAIL_REMINDER_DUE"] == "MAIL_REMINDER_DUE"
    assert len(set(values.values())) == len(values)  # no duplicates
    # notifications.notification_type is String(50)
    assert len("MAIL_REMINDER_DUE") <= 50


def test_reminders_do_not_trigger_real_emails():
    assert "MAIL_REMINDER_DUE" not in EMAIL_ELIGIBLE_NOTIFICATION_TYPES

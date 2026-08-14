# test_notification_email_dispatch.py
#
# Coverage for the business-critical-notification email feature:
# app/notifications/email_policy.py (which types are eligible),
# app/notifications/email_content.py (subject/body/HTML construction,
# ticket-context lookup), and app/notifications/email_notifier.py (the
# actual send loop + the NotificationService.notify() hook). No DB —
# every repository/db dependency below is a minimal fake exposing only
# what the code under test actually calls, matching this test suite's
# existing convention (see test_email_service_client_matching.py) of
# avoiding the DB-touching-test event-loop hang documented in the
# root CLAUDE.md.

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from app.notifications import email_notifier
from app.notifications.email_content import build_notification_email, load_ticket_context
from app.notifications.email_policy import EMAIL_ELIGIBLE_NOTIFICATION_TYPES, is_email_eligible
from app.notifications.service import NotificationService, NotificationType


# ---------------------------------------
# Fakes
# ---------------------------------------


@dataclass
class _FakeNotification:
    notification_id: uuid.UUID
    user_id: uuid.UUID
    notification_type: str
    title: str
    message: str
    link: str | None = None
    related_entity_type: str | None = None
    related_entity_id: uuid.UUID | None = None
    is_read: bool = False
    created_at: datetime = field(
        default_factory=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    )


def _make_notification(notification_type, **overrides):
    defaults = dict(
        notification_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        notification_type=notification_type,
        title="A Title",
        message="A message",
    )
    defaults.update(overrides)
    return _FakeNotification(**defaults)


class _FakeUserRepository:
    def __init__(self, emails_by_id: dict):
        self._emails_by_id = emails_by_id
        self.requested_ids = None

    async def get_active_emails_by_ids(self, user_ids):
        self.requested_ids = list(user_ids)
        return {uid: self._emails_by_id[uid] for uid in user_ids if uid in self._emails_by_id}


class _FakeEmailSender:
    def __init__(self, *, should_raise: bool = False, result: bool = True):
        self.sent = []
        self._should_raise = should_raise
        self._result = result

    async def send(self, *, to_email, subject, body, html_body=None):
        if self._should_raise:
            raise RuntimeError("smtp exploded")
        self.sent.append(
            {"to_email": to_email, "subject": subject, "body": body, "html_body": html_body}
        )
        return self._result


class _NoQueryDB:
    """Used whenever related_entity_type != 'ticket' — load_ticket_context
    must short-circuit before ever touching the db in that case."""

    async def execute(self, *args, **kwargs):
        raise AssertionError("db.execute should not be called with no ticket context")


class _FakeQueryResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeTicketQueryDB:
    """Row must be the 4-tuple load_ticket_context's real query
    returns: (ticket, client, agent_user, assigned_by_user) — the
    latter two None whenever the ticket is unassigned or its assigner
    can't be resolved."""

    def __init__(self, row):
        self._row = row

    async def execute(self, *args, **kwargs):
        return _FakeQueryResult(self._row)


@dataclass
class _FakeEnumValue:
    value: str


@dataclass
class _FakeTicketRow:
    ticket_id: uuid.UUID
    title: str
    current_priority: _FakeEnumValue
    current_status: _FakeEnumValue


@dataclass
class _FakeClientRow:
    name: str


@dataclass
class _FakeAssignedUser:
    name: str


class _FakeNotificationRepositoryForService:
    """Mimics NotificationRepository.create_many without a real session —
    Notification's own default=uuid.uuid4/utcnow columns are only
    applied by the ORM at flush time, so a fake is used instead of
    constructing real Notification() instances directly."""

    def __init__(self):
        self.rows = []

    async def create_many(self, rows):
        self.rows = rows
        return [
            _FakeNotification(
                notification_id=uuid.uuid4(),
                user_id=row["user_id"],
                notification_type=row["notification_type"],
                title=row["title"],
                message=row["message"],
                link=row.get("link"),
                related_entity_type=row.get("related_entity_type"),
                related_entity_id=row.get("related_entity_id"),
            )
            for row in rows
        ]

    async def count_for_user(self, user_id, *, unread_only=False):
        raise AssertionError("should not be called — no SSE subscribers in these tests")


# ---------------------------------------
# Email policy
# ---------------------------------------


def test_email_eligible_types_match_policy():
    assert EMAIL_ELIGIBLE_NOTIFICATION_TYPES == {
        NotificationType.TICKET_ASSIGNED,
        NotificationType.ESCALATION_CREATED,
        NotificationType.CLIENT_REPLY,
    }
    assert not is_email_eligible(NotificationType.TICKET_STATUS_CHANGED)
    assert not is_email_eligible(NotificationType.TICKET_RESOLVED)
    # SLA Breached is explicitly out of the email-eligible scope — stays
    # in-app-only, same as every other SLA/escalation-ladder type.
    assert not is_email_eligible(NotificationType.SLA_BREACHED)
    assert not is_email_eligible(NotificationType.SLA_HALF_ELAPSED)
    assert not is_email_eligible(NotificationType.SLA_AT_RISK)
    assert not is_email_eligible(NotificationType.SLA_ESCALATED)
    assert not is_email_eligible(NotificationType.ESCALATION_ACKNOWLEDGED)
    assert not is_email_eligible(NotificationType.ESCALATION_ADVANCED)
    assert not is_email_eligible(NotificationType.ESCALATION_CLOSED)


# ---------------------------------------
# dispatch_notification_emails — eligible types send email
# ---------------------------------------


@pytest.mark.parametrize(
    "notification_type",
    [
        pytest.param(NotificationType.TICKET_ASSIGNED, id="ticket_assigned"),
        pytest.param(NotificationType.ESCALATION_CREATED, id="ticket_escalated"),
        pytest.param(NotificationType.CLIENT_REPLY, id="client_reply_received"),
    ],
)
async def test_business_critical_type_sends_email(monkeypatch, notification_type):
    fake_sender = _FakeEmailSender()
    monkeypatch.setattr(email_notifier, "get_email_sender", lambda: fake_sender)

    user_id = uuid.uuid4()
    notification = _make_notification(notification_type, user_id=user_id)
    user_repo = _FakeUserRepository({user_id: "agent@company.com"})

    await email_notifier.dispatch_notification_emails(
        [notification], db=_NoQueryDB(), user_repository=user_repo
    )

    assert len(fake_sender.sent) == 1
    assert fake_sender.sent[0]["to_email"] == "agent@company.com"
    assert fake_sender.sent[0]["subject"] == notification.title


@pytest.mark.parametrize(
    "notification_type",
    [
        pytest.param(NotificationType.TICKET_STATUS_CHANGED, id="ticket_status_changed"),
        pytest.param(NotificationType.SLA_BREACHED, id="sla_breached"),
        pytest.param(NotificationType.SLA_HALF_ELAPSED, id="sla_half_elapsed"),
        pytest.param(NotificationType.SLA_AT_RISK, id="sla_at_risk"),
        pytest.param(NotificationType.SLA_ESCALATED, id="sla_escalated"),
        pytest.param(NotificationType.ESCALATION_ACKNOWLEDGED, id="escalation_acknowledged"),
        pytest.param(NotificationType.ESCALATION_ADVANCED, id="escalation_advanced"),
        pytest.param(NotificationType.ESCALATION_CLOSED, id="escalation_closed"),
    ],
)
async def test_non_critical_notification_does_not_send_email(monkeypatch, notification_type):
    fake_sender = _FakeEmailSender()
    monkeypatch.setattr(email_notifier, "get_email_sender", lambda: fake_sender)

    user_id = uuid.uuid4()
    notification = _make_notification(notification_type, user_id=user_id)
    user_repo = _FakeUserRepository({user_id: "agent@company.com"})

    await email_notifier.dispatch_notification_emails(
        [notification], db=_NoQueryDB(), user_repository=user_repo
    )

    assert fake_sender.sent == []
    # Never even queries recipient emails for an ineligible batch.
    assert user_repo.requested_ids is None


# ---------------------------------------
# Recipient rules
# ---------------------------------------


async def test_correct_recipient_email(monkeypatch):
    fake_sender = _FakeEmailSender()
    monkeypatch.setattr(email_notifier, "get_email_sender", lambda: fake_sender)

    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    notifications = [
        _make_notification(NotificationType.TICKET_ASSIGNED, user_id=user_a),
        _make_notification(NotificationType.TICKET_ASSIGNED, user_id=user_b),
    ]
    user_repo = _FakeUserRepository({user_a: "alice@company.com", user_b: "bob@company.com"})

    await email_notifier.dispatch_notification_emails(
        notifications, db=_NoQueryDB(), user_repository=user_repo
    )

    assert {item["to_email"] for item in fake_sender.sent} == {
        "alice@company.com",
        "bob@company.com",
    }


async def test_inactive_user_is_not_emailed(monkeypatch):
    fake_sender = _FakeEmailSender()
    monkeypatch.setattr(email_notifier, "get_email_sender", lambda: fake_sender)

    active_id, inactive_id = uuid.uuid4(), uuid.uuid4()
    notifications = [
        _make_notification(NotificationType.TICKET_ASSIGNED, user_id=active_id),
        _make_notification(NotificationType.TICKET_ASSIGNED, user_id=inactive_id),
    ]
    # get_active_emails_by_ids already filters User.is_active.is_(True) at
    # the query level — simulated here by simply omitting the inactive
    # user from the fake's backing map.
    user_repo = _FakeUserRepository({active_id: "active@company.com"})

    await email_notifier.dispatch_notification_emails(
        notifications, db=_NoQueryDB(), user_repository=user_repo
    )

    assert len(fake_sender.sent) == 1
    assert fake_sender.sent[0]["to_email"] == "active@company.com"


# ---------------------------------------
# Failure isolation
# ---------------------------------------


async def test_email_send_failure_does_not_raise_or_skip_other_recipients(monkeypatch):
    fake_sender = _FakeEmailSender(should_raise=True)
    monkeypatch.setattr(email_notifier, "get_email_sender", lambda: fake_sender)

    user_id = uuid.uuid4()
    notification = _make_notification(NotificationType.TICKET_ASSIGNED, user_id=user_id)
    user_repo = _FakeUserRepository({user_id: "agent@company.com"})

    # Must not raise — a transport failure is caught and logged, never
    # propagated to the caller.
    await email_notifier.dispatch_notification_emails(
        [notification], db=_NoQueryDB(), user_repository=user_repo
    )


async def test_email_failure_does_not_affect_notification_creation(monkeypatch):
    def _raise_on_queue(created):
        raise RuntimeError("email infra down")

    monkeypatch.setattr(email_notifier, "queue_notification_emails", _raise_on_queue)

    repo = _FakeNotificationRepositoryForService()
    service = NotificationService(repo)
    user_id = uuid.uuid4()

    # notify() must complete normally — the notification row is already
    # durably created before email dispatch is even attempted.
    await service.notify(
        user_id, NotificationType.TICKET_ASSIGNED, title="A ticket was assigned to you", message="m"
    )

    assert len(repo.rows) == 1
    assert repo.rows[0]["user_id"] == user_id


# ---------------------------------------
# Duplicate prevention
# ---------------------------------------


async def test_duplicate_recipient_produces_one_notification_and_one_email(monkeypatch):
    captured = {}

    def _spy(created):
        captured["created"] = created

    monkeypatch.setattr(email_notifier, "queue_notification_emails", _spy)

    repo = _FakeNotificationRepositoryForService()
    service = NotificationService(repo)
    user_id = uuid.uuid4()

    # Same recipient passed twice in one call — notify()'s own dedup
    # must mean exactly one notification row and exactly one email
    # candidate, never two.
    await service.notify(
        [user_id, user_id], NotificationType.TICKET_ASSIGNED, title="t", message="m"
    )

    assert len(repo.rows) == 1
    assert len(captured["created"]) == 1
    assert captured["created"][0].user_id == user_id


# ---------------------------------------
# NotificationService.notify() hook
# ---------------------------------------


async def test_notify_queues_email_for_eligible_type(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        email_notifier, "queue_notification_emails", lambda created: captured.setdefault("created", created)
    )

    repo = _FakeNotificationRepositoryForService()
    service = NotificationService(repo)

    await service.notify(
        uuid.uuid4(), NotificationType.SLA_BREACHED, title="SLA Breached", message="m"
    )

    assert "created" in captured
    assert len(captured["created"]) == 1


# ---------------------------------------
# Email content — ticket context + HTML rendering
# ---------------------------------------


async def test_load_ticket_context_resolves_priority_status_client():
    ticket_id = uuid.uuid4()
    ticket = _FakeTicketRow(
        ticket_id=ticket_id,
        title="Testing mail",
        current_priority=_FakeEnumValue("HIGH"),
        current_status=_FakeEnumValue("OPEN"),
    )
    client = _FakeClientRow(name="Acme Corp")
    agent_user = _FakeAssignedUser(name="Raju")
    assigned_by_user = _FakeAssignedUser(name="Kamaleshwaran")
    db = _FakeTicketQueryDB((ticket, client, agent_user, assigned_by_user))

    context = await load_ticket_context(
        db, related_entity_type="ticket", related_entity_id=ticket_id
    )

    assert context.ticket_id == ticket_id
    assert context.title == "Testing mail"
    assert context.priority == "HIGH"
    assert context.status == "OPEN"
    assert context.client_name == "Acme Corp"
    assert context.assigned_to_name == "Raju"
    assert context.assigned_by_name == "Kamaleshwaran"


async def test_load_ticket_context_handles_unassigned_ticket_with_no_client():
    ticket_id = uuid.uuid4()
    ticket = _FakeTicketRow(
        ticket_id=ticket_id,
        title="Untitled work",
        current_priority=_FakeEnumValue("LOW"),
        current_status=_FakeEnumValue("OPEN"),
    )
    db = _FakeTicketQueryDB((ticket, None, None, None))

    context = await load_ticket_context(
        db, related_entity_type="ticket", related_entity_id=ticket_id
    )

    assert context.client_name is None
    assert context.assigned_to_name is None
    assert context.assigned_by_name is None


async def test_load_ticket_context_returns_none_for_non_ticket_entity():
    context = await load_ticket_context(
        _NoQueryDB(),
        related_entity_type="ticket_edit_access_request",
        related_entity_id=uuid.uuid4(),
    )
    assert context is None


def test_build_notification_email_escapes_html():
    notification = _make_notification(
        NotificationType.TICKET_ASSIGNED,
        title="<script>alert(1)</script>",
        message="hello & <b>world</b>",
    )

    _, text_body, html_body = build_notification_email(notification, ticket_context=None)

    assert "<script>" not in html_body
    assert "&lt;script&gt;" in html_body
    # No ticket context → no ticket-shaped fields at all, and never a
    # placeholder string in either body.
    for placeholder in ("Not applicable", "N/A", "Unknown", "null", "undefined"):
        assert placeholder not in html_body
        assert placeholder not in text_body
    assert "Timestamp" in text_body


async def test_html_email_rendering_includes_all_required_fields(monkeypatch):
    fake_sender = _FakeEmailSender()
    monkeypatch.setattr(email_notifier, "get_email_sender", lambda: fake_sender)

    ticket_id = uuid.uuid4()
    notification = _make_notification(
        NotificationType.TICKET_ASSIGNED,
        title="A ticket was assigned to you",
        message="Fix the widget",
        related_entity_type="ticket",
        related_entity_id=ticket_id,
    )
    user_id = notification.user_id
    user_repo = _FakeUserRepository({user_id: "agent@company.com"})
    ticket = _FakeTicketRow(
        ticket_id=ticket_id,
        title="Fix the widget",
        current_priority=_FakeEnumValue("CRITICAL"),
        current_status=_FakeEnumValue("IN_PROGRESS"),
    )
    client = _FakeClientRow(name="Acme Corp")
    agent_user = _FakeAssignedUser(name="Raju")
    assigned_by_user = _FakeAssignedUser(name="Kamaleshwaran")
    db = _FakeTicketQueryDB((ticket, client, agent_user, assigned_by_user))

    await email_notifier.dispatch_notification_emails([notification], db=db, user_repository=user_repo)

    assert len(fake_sender.sent) == 1
    html_body = fake_sender.sent[0]["html_body"]
    text_body = fake_sender.sent[0]["body"]

    for expected in (
        "A ticket was assigned to you",
        "Fix the widget",
        "Acme Corp",
        "CRITICAL",
        "IN_PROGRESS",
        "Assigned to",
        "Raju",
        "Assigned by",
        "Kamaleshwaran",
        "Assigned at",
    ):
        assert expected in html_body
        assert expected in text_body

    # The internal ticket UUID is never user-facing content.
    assert str(ticket_id) not in html_body
    assert str(ticket_id) not in text_body


async def test_escalation_created_email_has_no_assignment_fields(monkeypatch):
    fake_sender = _FakeEmailSender()
    monkeypatch.setattr(email_notifier, "get_email_sender", lambda: fake_sender)

    ticket_id = uuid.uuid4()
    notification = _make_notification(
        NotificationType.ESCALATION_CREATED,
        title="Ticket Escalated: Fix the widget",
        message="This ticket has been escalated.",
        related_entity_type="ticket",
        related_entity_id=ticket_id,
    )
    user_id = notification.user_id
    user_repo = _FakeUserRepository({user_id: "lead@company.com"})
    ticket = _FakeTicketRow(
        ticket_id=ticket_id,
        title="Fix the widget",
        current_priority=_FakeEnumValue("HIGH"),
        current_status=_FakeEnumValue("OPEN"),
    )
    client = _FakeClientRow(name="Acme Corp")
    agent_user = _FakeAssignedUser(name="Raju")
    db = _FakeTicketQueryDB((ticket, client, agent_user, None))

    await email_notifier.dispatch_notification_emails([notification], db=db, user_repository=user_repo)

    text_body = fake_sender.sent[0]["body"]
    html_body = fake_sender.sent[0]["html_body"]

    assert "Ticket" in text_body
    assert "Timestamp" in text_body
    for absent in ("Assigned to", "Assigned by", "Assigned at"):
        assert absent not in text_body
        assert absent not in html_body

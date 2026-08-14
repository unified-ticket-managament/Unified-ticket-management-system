# test_escalation_service_email_dedup.py
#
# Regression coverage for a real pre-existing bug found while wiring up
# Graph-based notification email: EscalationService._notify_owners used
# to call sla_breach_notifier.send_notification_emails directly, in
# addition to notification_service.notify() — which duplicated the
# email for ESCALATION_CREATED (already email-eligible via the
# centralized policy) and sent an ungated email for
# ESCALATION_ACKNOWLEDGED/ADVANCED/CLOSED (none of which are supposed
# to email at all). No DB — EscalationService's own unrelated
# repository dependencies aren't touched by _notify_owners, so they're
# passed as None, matching the pure-logic-test convention established
# by test_notification_email_dispatch.py.

import uuid
from dataclasses import dataclass, field

import pytest

from app.notifications.service import NotificationType
from app.ticketing.services.escalation_service import EscalationService


@dataclass
class _FakeTicket:
    ticket_id: uuid.UUID
    title: str = "Some ticket"


class _FakeUserRepository:
    """resolve_global_inbox_user_ids' only dependency — no Site
    Lead/Super Admin in this test, so recipient_ids == owner_ids."""

    async def list_active_by_role_name(self, role_name):
        return []


class _SpyNotificationService:
    def __init__(self):
        self.calls = []

    async def notify(self, user_ids, notification_type, *, title, message, **kwargs):
        self.calls.append({"user_ids": set(user_ids), "notification_type": notification_type})


def _build_service(notification_service) -> EscalationService:
    return EscalationService(
        ticket_escalation_repository=None,
        ticket_repository=None,
        resolution_sla_repository=None,
        sla_policy_repository=None,
        user_repository=_FakeUserRepository(),
        audit_log_repository=None,
        notification_service=notification_service,
    )


@pytest.mark.parametrize(
    "notification_type",
    [
        NotificationType.ESCALATION_CREATED,
        NotificationType.ESCALATION_ACKNOWLEDGED,
        NotificationType.ESCALATION_ADVANCED,
        NotificationType.ESCALATION_CLOSED,
    ],
)
async def test_notify_owners_only_calls_notification_service_never_email_directly(
    monkeypatch, notification_type
):
    # If _notify_owners ever calls get_email_sender()/send_notification_emails
    # directly again, this fails loudly — no code path in
    # escalation_service.py should reach for an EmailSender at all;
    # NotificationService.notify() is the only thing that may cause an
    # email to be sent, gated by app/notifications/email_policy.py.
    email_sender_calls = []

    class _SpyEmailSender:
        async def send(self, **kwargs):
            email_sender_calls.append(kwargs)
            return True

    monkeypatch.setattr(
        "app.core.email_sender.get_email_sender", lambda: _SpyEmailSender()
    )

    notification_service = _SpyNotificationService()
    service = _build_service(notification_service)
    owner_id = uuid.uuid4()
    ticket = _FakeTicket(ticket_id=uuid.uuid4())

    await service._notify_owners(
        ticket=ticket,
        owner_ids={owner_id},
        notification_type=notification_type,
        title="An escalation event",
        message="Something happened",
    )

    assert len(notification_service.calls) == 1
    assert notification_service.calls[0]["user_ids"] == {owner_id}
    assert notification_service.calls[0]["notification_type"] == notification_type
    assert email_sender_calls == []

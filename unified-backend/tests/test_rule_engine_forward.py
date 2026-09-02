# test_rule_engine_forward.py
#
# Pure-logic coverage for RuleEngineService._forward_to_employees —
# the mechanism behind the "Forwarding" bug fix: a recipient must only
# receive the in-app MAIL_RULE_FORWARDED/OTP_FORWARDED notification if
# their own real outbound send actually succeeded, never the previous
# unconditional-notify-everyone behavior. No DB — user_repository and
# notification_service are minimal fakes exposing only what the method
# calls, same convention as test_forward_to_internal_user.py.

from uuid import uuid4

import pytest

from app.ticketing.enums.rule_enums import RuleCategory
from app.ticketing.services.rule_engine_service import RuleEngineService


class _FakeUserRepository:
    def __init__(self, emails_by_id):
        self._emails_by_id = emails_by_id

    async def get_active_emails_by_ids(self, user_ids):
        return {uid: self._emails_by_id[uid] for uid in user_ids if uid in self._emails_by_id}


class _FakeNotificationRepository:
    """
    Tracks (user_id, related_entity_id, notification_type) tuples that
    a _FakeNotificationService.notify() call above has actually
    recorded — mirrors the real NotificationRepository.
    exists_for_related_entity query closely enough to test
    _forward_to_employees' durable dedup guard without a real DB.
    """

    def __init__(self):
        self.existing: set[tuple] = set()

    async def exists_for_related_entity(self, user_id, related_entity_id, notification_types):
        return any(
            (user_id, related_entity_id, nt) in self.existing for nt in notification_types
        )


class _FakeNotificationService:
    def __init__(self, repository: "_FakeNotificationRepository | None" = None):
        self.calls = []
        self._repository = repository

    async def notify(self, user_ids, notification_type, title, message, **kwargs):
        self.calls.append(
            {
                "user_ids": set(user_ids),
                "notification_type": notification_type,
                "title": title,
                "message": message,
                **kwargs,
            }
        )
        if self._repository is not None:
            related_entity_id = kwargs.get("related_entity_id")
            for uid in user_ids:
                self._repository.existing.add((uid, related_entity_id, notification_type))


class _FakeInteraction:
    def __init__(self, interaction_id, payload):
        self.interaction_id = interaction_id
        self.payload = payload


class _SelectiveFailureMailProvider:
    """Fails send_email for one specific recipient email, succeeds for every other."""

    def __init__(self, failing_email):
        self._failing_email = failing_email
        self.sent_to = []

    async def send_email(self, envelope):
        if envelope.to_email == self._failing_email:
            raise RuntimeError("simulated send failure")
        self.sent_to.append(envelope.to_email)
        return None


class _AlwaysFailingMailProvider:
    async def send_email(self, envelope):
        raise RuntimeError("simulated send failure")


def _make_service(
    user_repository,
    notification_service,
    mail_provider,
    monkeypatch,
    notification_repository=None,
):
    service = RuleEngineService(
        rule_repository=None,
        mail_folder_repository=None,
        interaction_repository=None,
        user_repository=user_repository,
        notification_service=notification_service,
        notification_repository=notification_repository,
    )
    monkeypatch.setattr(
        "app.ticketing.services.rule_engine_service.get_mail_provider_client",
        lambda settings: mail_provider,
    )
    return service


class TestForwardToEmployeesPartialFailure:
    async def test_notify_gets_only_the_successful_subset(self, monkeypatch):
        succeeding_id = uuid4()
        failing_id = uuid4()
        emails_by_id = {
            succeeding_id: "succeeds@probeps.com",
            failing_id: "fails@probeps.com",
        }
        mail_provider = _SelectiveFailureMailProvider(failing_email="fails@probeps.com")
        notification_service = _FakeNotificationService()
        service = _make_service(
            _FakeUserRepository(emails_by_id), notification_service, mail_provider, monkeypatch
        )
        interaction = _FakeInteraction(
            uuid4(),
            {"subject": "Test subject", "body": "Test body", "from_email": "client@example.com"},
        )

        await service._forward_to_employees(
            [succeeding_id, failing_id],
            interaction=interaction,
            rule_category=RuleCategory.MAIL_RULE,
        )

        assert len(notification_service.calls) == 1
        call = notification_service.calls[0]
        assert call["user_ids"] == {succeeding_id}
        assert call["related_entity_type"] == "interaction"
        assert call["related_entity_id"] == interaction.interaction_id
        assert call["link"] == f"/inbox?interaction_id={interaction.interaction_id}"

    async def test_all_fail_notify_never_called(self, monkeypatch):
        recipient_id = uuid4()
        emails_by_id = {recipient_id: "fails@probeps.com"}
        notification_service = _FakeNotificationService()
        service = _make_service(
            _FakeUserRepository(emails_by_id),
            notification_service,
            _AlwaysFailingMailProvider(),
            monkeypatch,
        )
        interaction = _FakeInteraction(
            uuid4(),
            {"subject": "Test subject", "body": "Test body", "from_email": "client@example.com"},
        )

        await service._forward_to_employees(
            [recipient_id],
            interaction=interaction,
            rule_category=RuleCategory.MAIL_RULE,
        )

        assert notification_service.calls == []

    async def test_all_succeed_notifies_everyone(self, monkeypatch):
        first_id = uuid4()
        second_id = uuid4()
        emails_by_id = {first_id: "first@probeps.com", second_id: "second@probeps.com"}
        mail_provider = _SelectiveFailureMailProvider(failing_email="nobody@probeps.com")
        notification_service = _FakeNotificationService()
        service = _make_service(
            _FakeUserRepository(emails_by_id), notification_service, mail_provider, monkeypatch
        )
        interaction = _FakeInteraction(
            uuid4(),
            {"subject": "Test subject", "body": "Test body", "from_email": "client@example.com"},
        )

        await service._forward_to_employees(
            [first_id, second_id],
            interaction=interaction,
            rule_category=RuleCategory.OTP_RULE,
        )

        assert len(notification_service.calls) == 1
        assert notification_service.calls[0]["user_ids"] == {first_id, second_id}
        assert notification_service.calls[0]["notification_type"] == "OTP_FORWARDED"

    async def test_no_active_recipients_resolved_notify_never_called(self, monkeypatch):
        # None of the selected employee ids resolve to an active user
        # at all (e.g. all deactivated since the rule was configured)
        # — must return before ever touching the mail provider.
        notification_service = _FakeNotificationService()
        service = _make_service(
            _FakeUserRepository({}), notification_service, _AlwaysFailingMailProvider(), monkeypatch
        )
        interaction = _FakeInteraction(
            uuid4(),
            {"subject": "Test subject", "body": "Test body", "from_email": "client@example.com"},
        )

        await service._forward_to_employees(
            [uuid4()],
            interaction=interaction,
            rule_category=RuleCategory.MAIL_RULE,
        )

        assert notification_service.calls == []


class TestForwardToEmployeesDeduplication:
    """
    Coverage for the mail-routing-duplication fix: a destination
    employee must only ever be forwarded a given source interaction
    once, regardless of how many rules/actions/pipeline runs resolve
    to them.
    """

    async def test_two_actions_in_one_call_share_the_in_call_dedup_set(self, monkeypatch):
        # Simulates one rule with two FORWARD_TO actions (e.g. the same
        # employee named directly in one action and reachable via a
        # distribution list in another) — both calls share the same
        # `forwarded_user_ids` set the way evaluate_and_execute_for_email
        # threads it through every matched action for one email.
        employee_id = uuid4()
        emails_by_id = {employee_id: "employee@probeps.com"}
        mail_provider = _SelectiveFailureMailProvider(failing_email="nobody@probeps.com")
        notification_service = _FakeNotificationService()
        service = _make_service(
            _FakeUserRepository(emails_by_id), notification_service, mail_provider, monkeypatch
        )
        interaction = _FakeInteraction(
            uuid4(),
            {"subject": "Test subject", "body": "Test body", "from_email": "client@example.com"},
        )
        forwarded_user_ids: set = set()

        await service._forward_to_employees(
            [employee_id],
            interaction=interaction,
            rule_category=RuleCategory.MAIL_RULE,
            forwarded_user_ids=forwarded_user_ids,
        )
        await service._forward_to_employees(
            [employee_id],
            interaction=interaction,
            rule_category=RuleCategory.MAIL_RULE,
            forwarded_user_ids=forwarded_user_ids,
        )

        assert len(mail_provider.sent_to) == 1
        assert len(notification_service.calls) == 1

    async def test_two_separate_calls_are_deduped_by_the_durable_notification_check(
        self, monkeypatch
    ):
        # Simulates two independent evaluate_and_execute_for_email
        # invocations for the SAME interaction (e.g. two separately
        # enabled rules each matching and forwarding, or a retried/
        # redelivered pipeline run) — each gets its own fresh in-call
        # `forwarded_user_ids` set, so only the durable
        # notification_repository check can catch this case.
        employee_id = uuid4()
        emails_by_id = {employee_id: "employee@probeps.com"}
        mail_provider = _SelectiveFailureMailProvider(failing_email="nobody@probeps.com")
        notification_repository = _FakeNotificationRepository()
        notification_service = _FakeNotificationService(notification_repository)
        service = _make_service(
            _FakeUserRepository(emails_by_id),
            notification_service,
            mail_provider,
            monkeypatch,
            notification_repository=notification_repository,
        )
        interaction = _FakeInteraction(
            uuid4(),
            {"subject": "Test subject", "body": "Test body", "from_email": "client@example.com"},
        )

        await service._forward_to_employees(
            [employee_id],
            interaction=interaction,
            rule_category=RuleCategory.MAIL_RULE,
            forwarded_user_ids=set(),
        )
        await service._forward_to_employees(
            [employee_id],
            interaction=interaction,
            rule_category=RuleCategory.MAIL_RULE,
            forwarded_user_ids=set(),
        )

        assert len(mail_provider.sent_to) == 1
        assert len(notification_service.calls) == 1

    async def test_different_interactions_are_not_deduped_against_each_other(self, monkeypatch):
        # A stable-id-based guard must never suppress a genuinely
        # different source email to the same employee just because an
        # earlier, unrelated interaction was already forwarded to them.
        employee_id = uuid4()
        emails_by_id = {employee_id: "employee@probeps.com"}
        mail_provider = _SelectiveFailureMailProvider(failing_email="nobody@probeps.com")
        notification_repository = _FakeNotificationRepository()
        notification_service = _FakeNotificationService(notification_repository)
        service = _make_service(
            _FakeUserRepository(emails_by_id),
            notification_service,
            mail_provider,
            monkeypatch,
            notification_repository=notification_repository,
        )
        first_interaction = _FakeInteraction(
            uuid4(), {"subject": "First", "body": "Body one", "from_email": "client@example.com"}
        )
        second_interaction = _FakeInteraction(
            uuid4(), {"subject": "Second", "body": "Body two", "from_email": "client@example.com"}
        )

        await service._forward_to_employees(
            [employee_id],
            interaction=first_interaction,
            rule_category=RuleCategory.MAIL_RULE,
            forwarded_user_ids=set(),
        )
        await service._forward_to_employees(
            [employee_id],
            interaction=second_interaction,
            rule_category=RuleCategory.MAIL_RULE,
            forwarded_user_ids=set(),
        )

        assert len(mail_provider.sent_to) == 2
        assert len(notification_service.calls) == 2

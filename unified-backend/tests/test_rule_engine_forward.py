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
    def __init__(self, emails_by_id, names_by_id=None):
        self._emails_by_id = emails_by_id
        self._names_by_id = names_by_id or {}

    async def get_active_emails_by_ids(self, user_ids):
        return {uid: self._emails_by_id[uid] for uid in user_ids if uid in self._emails_by_id}

    async def get_names_by_ids(self, user_ids):
        return {uid: self._names_by_id[uid] for uid in user_ids if uid in self._names_by_id}


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
    def __init__(self, interaction_id, payload, ticket_id=None, client_id=None, category_id=None):
        self.interaction_id = interaction_id
        self.payload = payload
        self.ticket_id = ticket_id
        self.client_id = client_id
        self.category_id = category_id


class _FakeCreatedInteraction:
    """What InteractionRepository.create(...) hands back — only the
    one field _forward_to_employees actually reads afterward
    (entity_id=forward_interaction.interaction_id) needs to be real."""

    def __init__(self, interaction_id):
        self.interaction_id = interaction_id


class _FakeInteractionRepository:
    """
    Records every InteractionCreate passed to .create(...) so tests can
    assert on the shape of the Interaction B a Rule-forward now
    produces, without a real DB. `.db` is a bare placeholder object —
    AuditLogService.log_event is monkeypatched out in _make_service
    below, so nothing here ever actually touches it.
    """

    class _FakeDb:
        pass

    def __init__(self):
        self.created: list = []
        self.returned: list = []
        self.db = self._FakeDb()

    async def create(self, data):
        self.created.append(data)
        result = _FakeCreatedInteraction(uuid4())
        self.returned.append(result)
        return result


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


async def _noop_log_event(*args, **kwargs):
    """
    Audit logging is exercised separately (TestForwardToEmployeesCreatesInteractionB
    below asserts on it directly by NOT patching it out) — every other
    test in this file is about notification fan-out/dedup, unrelated to
    the audit row, so this keeps them decoupled from AuditLogRepository/
    a real DB session.
    """
    return None


def _make_service(
    user_repository,
    notification_service,
    mail_provider,
    monkeypatch,
    notification_repository=None,
    interaction_repository=None,
    patch_audit_log=True,
):
    service = RuleEngineService(
        rule_repository=None,
        mail_folder_repository=None,
        interaction_repository=interaction_repository or _FakeInteractionRepository(),
        user_repository=user_repository,
        notification_service=notification_service,
        notification_repository=notification_repository,
    )
    monkeypatch.setattr(
        "app.ticketing.services.rule_engine_service.get_mail_provider_client",
        lambda settings: mail_provider,
    )
    if patch_audit_log:
        monkeypatch.setattr(
            "app.ticketing.services.rule_engine_service.AuditLogService.log_event",
            _noop_log_event,
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


class TestForwardToEmployeesCreatesInteractionB:
    """
    Coverage for the Decision 1/Decision 2 change: a Rule-forward now
    creates a real Interaction B, shaped identically to a manual
    forward, so the existing forward-recipient access mechanism picks
    it up automatically.
    """

    async def test_one_interaction_created_per_action_not_per_recipient(self, monkeypatch):
        first_id, second_id = uuid4(), uuid4()
        emails_by_id = {first_id: "first@probeps.com", second_id: "second@probeps.com"}
        mail_provider = _SelectiveFailureMailProvider(failing_email="nobody@probeps.com")
        interaction_repository = _FakeInteractionRepository()
        service = _make_service(
            _FakeUserRepository(emails_by_id),
            _FakeNotificationService(),
            mail_provider,
            monkeypatch,
            interaction_repository=interaction_repository,
        )
        original = _FakeInteraction(
            uuid4(),
            {"subject": "Test subject", "body": "Test body", "from_email": "client@example.com"},
        )

        await service._forward_to_employees(
            [first_id, second_id],
            interaction=original,
            rule_category=RuleCategory.MAIL_RULE,
        )

        assert len(interaction_repository.created) == 1

    async def test_b_is_shaped_like_a_forward_linked_to_the_original(self, monkeypatch):
        recipient_id = uuid4()
        emails_by_id = {recipient_id: "recipient@probeps.com"}
        interaction_repository = _FakeInteractionRepository()
        service = _make_service(
            _FakeUserRepository(emails_by_id, names_by_id={recipient_id: "Recipient Name"}),
            _FakeNotificationService(),
            _SelectiveFailureMailProvider(failing_email="nobody@probeps.com"),
            monkeypatch,
            interaction_repository=interaction_repository,
        )
        original = _FakeInteraction(
            uuid4(),
            {"subject": "Test subject", "body": "Test body", "from_email": "client@example.com"},
            ticket_id=uuid4(),
            client_id=uuid4(),
            category_id=None,
        )

        await service._forward_to_employees(
            [recipient_id],
            interaction=original,
            rule_category=RuleCategory.MAIL_RULE,
        )

        assert len(interaction_repository.created) == 1
        created = interaction_repository.created[0]
        assert created.interaction_type == "FORWARD"
        assert created.parent_interaction_id == original.interaction_id
        assert created.ticket_id == original.ticket_id
        assert created.client_id == original.client_id
        assert created.category_id == original.category_id
        from app.ticketing.enums import InteractionStatus

        assert created.status == InteractionStatus.ASSIGNED
        recipients = created.payload["recipients"]
        assert len(recipients) == 1
        assert recipients[0]["user_id"] == str(recipient_id)
        assert recipients[0]["email"] == "recipient@probeps.com"
        assert recipients[0]["name"] == "Recipient Name"

    async def test_only_succeeded_recipients_are_recorded_on_b(self, monkeypatch):
        # The exact Decision-1 caveat: a recipient whose real send
        # failed must never end up in payload.recipients, or they'd
        # gain forward-recipient reply access to mail they never
        # actually received.
        succeeding_id, failing_id = uuid4(), uuid4()
        emails_by_id = {
            succeeding_id: "succeeds@probeps.com",
            failing_id: "fails@probeps.com",
        }
        interaction_repository = _FakeInteractionRepository()
        service = _make_service(
            _FakeUserRepository(emails_by_id),
            _FakeNotificationService(),
            _SelectiveFailureMailProvider(failing_email="fails@probeps.com"),
            monkeypatch,
            interaction_repository=interaction_repository,
        )
        original = _FakeInteraction(
            uuid4(),
            {"subject": "Test subject", "body": "Test body", "from_email": "client@example.com"},
        )

        await service._forward_to_employees(
            [succeeding_id, failing_id],
            interaction=original,
            rule_category=RuleCategory.MAIL_RULE,
        )

        recipients = interaction_repository.created[0].payload["recipients"]
        recorded_ids = {r["user_id"] for r in recipients}
        assert recorded_ids == {str(succeeding_id)}
        assert str(failing_id) not in recorded_ids

    async def test_all_sends_fail_no_interaction_created(self, monkeypatch):
        recipient_id = uuid4()
        emails_by_id = {recipient_id: "fails@probeps.com"}
        interaction_repository = _FakeInteractionRepository()
        service = _make_service(
            _FakeUserRepository(emails_by_id),
            _FakeNotificationService(),
            _AlwaysFailingMailProvider(),
            monkeypatch,
            interaction_repository=interaction_repository,
        )
        original = _FakeInteraction(
            uuid4(),
            {"subject": "Test subject", "body": "Test body", "from_email": "client@example.com"},
        )

        await service._forward_to_employees(
            [recipient_id],
            interaction=original,
            rule_category=RuleCategory.MAIL_RULE,
        )

        assert interaction_repository.created == []

    async def test_audit_log_written_for_the_new_interaction(self, monkeypatch):
        recipient_id = uuid4()
        emails_by_id = {recipient_id: "recipient@probeps.com"}
        interaction_repository = _FakeInteractionRepository()
        audit_calls = []

        async def _recording_log_event(*args, **kwargs):
            audit_calls.append(kwargs)
            return None

        service = _make_service(
            _FakeUserRepository(emails_by_id),
            _FakeNotificationService(),
            _SelectiveFailureMailProvider(failing_email="nobody@probeps.com"),
            monkeypatch,
            interaction_repository=interaction_repository,
            patch_audit_log=False,
        )
        monkeypatch.setattr(
            "app.ticketing.services.rule_engine_service.AuditLogService.log_event",
            _recording_log_event,
        )
        original = _FakeInteraction(
            uuid4(),
            {"subject": "Test subject", "body": "Test body", "from_email": "client@example.com"},
        )

        await service._forward_to_employees(
            [recipient_id],
            interaction=original,
            rule_category=RuleCategory.MAIL_RULE,
        )

        assert len(audit_calls) == 1
        from app.ticketing.enums import AuditEntityType, AuditEventType

        assert audit_calls[0]["entity_type"] == AuditEntityType.INTERACTION
        assert audit_calls[0]["event_type"] == AuditEventType.REPLY_ADDED
        # entity_id is the newly-created B's own id, not the original's.
        assert audit_calls[0]["entity_id"] == interaction_repository.returned[0].interaction_id
        assert audit_calls[0]["entity_id"] != original.interaction_id

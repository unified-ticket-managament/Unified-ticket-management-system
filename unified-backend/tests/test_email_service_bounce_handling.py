# test_email_service_bounce_handling.py
#
# Phase 2 hardening: a message already classified as a bounce/NDR
# (EmailRequest.is_bounce=True, set by mail_mapping_service via
# bounce_detection.is_bounce_notification) must never create a normal
# ticket, run Mail Rules, or start an SLA clock — see EmailService.
# _receive_bounce's own docstring for the anti-loop rationale. No DB —
# same minimal-fake convention as test_email_service_category_matching.py.

from uuid import uuid4

from app.core.config import Settings
from app.ticketing.enums import InteractionStatus
from app.ticketing.schemas.email import EmailRequest
from app.ticketing.services.email_service import EmailService


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="postgresql+asyncpg://user:pass@localhost/test",
        jwt_secret_key="test-secret",
        sla_sweep_shared_secret="test-sweep-secret",
        graph_mailbox_address="ticketing@probeps.com",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


class _FakeClient:
    def __init__(self, client_id, name, inbox_email, account_manager_id):
        self.client_id = client_id
        self.name = name
        self.inbox_email = inbox_email
        self.account_manager_id = account_manager_id


class _FakeUser:
    def __init__(self, user_id):
        self.user_id = user_id


class _FakeDB:
    def add(self, obj):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass


class _FakeClientRepository:
    def __init__(self, clients_by_email=None):
        self._clients_by_email = clients_by_email or {}

    async def get_active_by_inbox_email(self, email_address):
        return self._clients_by_email.get(email_address.strip().lower())

    async def get_active_by_any_email(self, email_address):
        return await self.get_active_by_inbox_email(email_address)


class _FakeCategoryRepository:
    def __init__(self, categories_by_email=None):
        self._categories_by_email = categories_by_email or {}

    async def get_active_by_inbox_email(self, email_address):
        return self._categories_by_email.get(email_address.strip().lower())


class _FakeInteractionRepository:
    def __init__(self):
        self.db = _FakeDB()
        self.created = []

    async def exists_by_message_id(self, message_id):
        return False

    async def get_by_conversation_id(self, conversation_id):
        return []

    async def get_by_message_ids(self, message_ids):
        return []

    async def find_orphans_awaiting_parent(self, message_id):
        return []

    async def create(self, interaction_create):
        class _Created:
            pass

        created = _Created()
        created.interaction_id = uuid4()
        created.status = interaction_create.status
        self.created.append(interaction_create)
        return created


class _FakeUserRepository:
    def __init__(self, users_by_role=None):
        self._users_by_role = users_by_role or {}

    async def list_active_by_role_name(self, role_name):
        return self._users_by_role.get(role_name, [])

    async def get_by_id(self, user_id):
        return None


class _FakeNotificationService:
    def __init__(self):
        self.calls = []

    async def notify(self, recipient_ids, notification_type, **kwargs):
        self.calls.append((set(recipient_ids), notification_type, kwargs))


class _NeverCalledRuleEngineService:
    async def evaluate_and_execute_for_email(self, **kwargs):
        raise AssertionError("Rule engine must never run for a detected bounce/NDR")


class _NeverCalledSLAService:
    async def start_first_response_clock(self, **kwargs):
        raise AssertionError("SLA clock must never start for a detected bounce/NDR")

    async def resume_resolution_clock(self, **kwargs):
        raise AssertionError("SLA clock must never resume for a detected bounce/NDR")

    async def complete_first_response_clock(self, **kwargs):
        raise AssertionError("SLA clock must never complete for a detected bounce/NDR")


class _RecordingRuleEngineService:
    def __init__(self):
        self.calls = 0

    async def evaluate_and_execute_for_email(self, **kwargs):
        self.calls += 1


class _RecordingSLAService:
    def __init__(self):
        self.start_first_response_calls = 0

    async def start_first_response_clock(self, **kwargs):
        self.start_first_response_calls += 1

    async def resume_resolution_clock(self, **kwargs):
        pass

    async def complete_first_response_clock(self, **kwargs):
        pass


def _bounce_request(**overrides) -> EmailRequest:
    base = dict(
        to_email="ticketing@probeps.com",
        landed_mailbox="ticketing@probeps.com",
        from_email="mailer-daemon@example.com",
        subject="Undeliverable: your message",
        body="This is an automatically generated Delivery Status Notification.",
        message_id=f"<{uuid4().hex}@example.com>",
        is_bounce=True,
    )
    base.update(overrides)
    return EmailRequest(**base)


def _client_request(**overrides) -> EmailRequest:
    base = dict(
        to_email="ticketing@probeps.com",
        landed_mailbox="ticketing@probeps.com",
        from_email="patient@example.com",
        from_name="A Patient",
        subject="Question about my account",
        body="Hi, I have a question.",
        message_id=f"<{uuid4().hex}@example.com>",
    )
    base.update(overrides)
    return EmailRequest(**base)


async def test_bounce_skips_rule_engine_and_sla_and_creates_hidden_interaction(monkeypatch):
    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    site_lead_id = uuid4()
    interaction_repository = _FakeInteractionRepository()
    notification_service = _FakeNotificationService()

    service = EmailService(
        interaction_repository=interaction_repository,
        client_repository=_FakeClientRepository(),
        attachment_service=None,
        user_repository=_FakeUserRepository({"Site Lead": [_FakeUser(site_lead_id)]}),
        notification_service=notification_service,
        sla_service=_NeverCalledSLAService(),
        rule_engine_service=_NeverCalledRuleEngineService(),
        category_repository=_FakeCategoryRepository(),
    )

    response = await service.receive_email(_bounce_request())

    # No ticket, no thread — a bounce is never attached to any ticket.
    assert response.ticket_id is None
    assert response.threaded_under is None
    assert response.status == InteractionStatus.PENDING.value

    assert len(interaction_repository.created) == 1
    created = interaction_repository.created[0]
    assert created.is_bounce is True
    assert created.is_visible is False
    assert created.ticket_id is None
    assert created.parent_interaction_id is None

    # Exactly one notification, to the global-inbox audience only.
    assert len(notification_service.calls) == 1
    recipient_ids, notification_type, kwargs = notification_service.calls[0]
    assert notification_type == "MAIL_BOUNCE_DETECTED"
    assert recipient_ids == {site_lead_id}


async def test_bounce_notification_never_reaches_client_account_manager(monkeypatch):
    """
    Even when the bounce's sender/mailbox happens to resolve to a real
    Client, the notification audience must stay Site Lead/Super Admin
    only — never the client's own Account Manager, since a bounce is
    not real correspondence from them.
    """

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    account_manager_id = uuid4()
    site_lead_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="Family First",
        inbox_email="familyfirst@probeps.com",
        account_manager_id=account_manager_id,
    )

    notification_service = _FakeNotificationService()

    service = EmailService(
        interaction_repository=_FakeInteractionRepository(),
        client_repository=_FakeClientRepository({"familyfirst@probeps.com": client}),
        attachment_service=None,
        user_repository=_FakeUserRepository({"Site Lead": [_FakeUser(site_lead_id)]}),
        notification_service=notification_service,
        sla_service=_NeverCalledSLAService(),
        rule_engine_service=_NeverCalledRuleEngineService(),
        category_repository=_FakeCategoryRepository(),
    )

    await service.receive_email(
        _bounce_request(
            to_email="familyfirst@probeps.com",
            landed_mailbox="familyfirst@probeps.com",
        )
    )

    assert len(notification_service.calls) == 1
    recipient_ids, _, _ = notification_service.calls[0]
    assert recipient_ids == {site_lead_id}
    assert account_manager_id not in recipient_ids


async def test_non_bounce_email_completely_unaffected(monkeypatch):
    """
    Regression guard: is_bounce=False (the default for every existing
    caller) must go through the normal flow unchanged — rule engine
    runs, SLA clock starts, ticket-eligible normal MAIL_RECEIVED
    notification fires.
    """

    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    account_manager_id = uuid4()
    client = _FakeClient(
        client_id=uuid4(),
        name="Family First",
        inbox_email="familyfirst@probeps.com",
        account_manager_id=account_manager_id,
    )

    rule_engine_service = _RecordingRuleEngineService()
    sla_service = _RecordingSLAService()
    notification_service = _FakeNotificationService()
    interaction_repository = _FakeInteractionRepository()

    service = EmailService(
        interaction_repository=interaction_repository,
        client_repository=_FakeClientRepository({"familyfirst@probeps.com": client}),
        attachment_service=None,
        user_repository=_FakeUserRepository({}),
        notification_service=notification_service,
        sla_service=sla_service,
        rule_engine_service=rule_engine_service,
        category_repository=_FakeCategoryRepository(),
    )

    response = await service.receive_email(
        _client_request(
            to_email="familyfirst@probeps.com",
            landed_mailbox="familyfirst@probeps.com",
        )
    )

    assert response.client_id == str(client.client_id)
    assert rule_engine_service.calls == 1
    assert sla_service.start_first_response_calls == 1

    assert len(interaction_repository.created) == 1
    created = interaction_repository.created[0]
    assert created.is_bounce is False
    assert created.is_visible is True

    assert len(notification_service.calls) == 1
    _, notification_type, _ = notification_service.calls[0]
    assert notification_type == "MAIL_RECEIVED"

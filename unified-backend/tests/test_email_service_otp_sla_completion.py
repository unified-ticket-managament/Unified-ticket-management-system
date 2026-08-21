# test_email_service_otp_sla_completion.py
#
# Focused coverage for EmailService.receive_email's OTP -> Response
# SLA completion wiring: completion is now decided by the semantic
# classifier (app.ticketing.services.otp_classifier), never by
# whether an OTP Rule is configured/matches, and always runs before
# the Mail/OTP Rules pass (so it never depends on that pass, or its
# forward_to action's send, succeeding). No DB — every repository/
# service dependency below is a minimal fake exposing only what
# receive_email actually calls, same convention as
# test_email_service_client_matching.py.

from uuid import uuid4

from app.core.config import Settings
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


class _FakeDB:
    def add(self, obj):
        pass

    async def flush(self):
        pass

    async def refresh(self, obj):
        pass


class _FakeClientRepository:
    async def get_active_by_inbox_email(self, email_address):
        return None

    async def get_active_by_any_email(self, email_address):
        return None


class _FakeInteractionRepository:
    def __init__(self):
        self.db = _FakeDB()

    async def exists_by_message_id(self, message_id):
        return False

    async def get_by_conversation_id(self, conversation_id):
        return []

    async def get_by_message_ids(self, message_ids):
        return []

    async def create(self, interaction_create):
        class _Created:
            pass

        created = _Created()
        created.interaction_id = uuid4()
        created.status = interaction_create.status
        return created


class _FakeUserRepository:
    async def list_active_by_role_name(self, role_name):
        return []

    async def get_by_id(self, user_id):
        return None


class _FakeNotificationService:
    async def notify(self, recipient_ids, notification_type, **kwargs):
        pass


class _FakeSLAService:
    def __init__(self):
        self.completed_calls = []

    async def start_first_response_clock(self, *, interaction):
        pass

    async def resume_resolution_clock(self, *, ticket_id, triggering_interaction_id):
        pass

    async def complete_first_response_clock(self, *, interaction_id, completion_reason, resulting_ticket_id=None):
        self.completed_calls.append(
            {
                "interaction_id": interaction_id,
                "completion_reason": completion_reason,
                "resulting_ticket_id": resulting_ticket_id,
            }
        )


class _FakeRuleEngineService:
    """
    Records that it was called (and when, relative to SLA completion)
    via a shared `call_log` list every test passes in — mirrors what
    the real RuleEngineService does (match rules, run actions,
    swallow forward failures internally) without any of the DB/Graph
    machinery.
    """

    def __init__(self, call_log, raises: bool = False):
        self._call_log = call_log
        self._raises = raises

    async def evaluate_and_execute_for_email(self, *, interaction, context):
        self._call_log.append("rule_engine_called")
        if self._raises:
            raise RuntimeError("forward failed")
        return True


def _email_request(**overrides) -> EmailRequest:
    base = dict(
        to_email="ticketing@probeps.com",
        from_email="client@example.com",
        from_name="Client",
        subject="Question about billing",
        body="Hi, I have a question.",
        message_id=f"<{uuid4().hex}@example.com>",
    )
    base.update(overrides)
    return EmailRequest(**base)


def _build_service(monkeypatch, *, sla_service=None, rule_engine_service=None):
    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings",
        lambda: _settings(),
    )

    return EmailService(
        interaction_repository=_FakeInteractionRepository(),
        client_repository=_FakeClientRepository(),
        attachment_service=None,
        user_repository=_FakeUserRepository(),
        notification_service=_FakeNotificationService(),
        sla_service=sla_service,
        rule_engine_service=rule_engine_service,
    )


_GENUINE_OTP_EMAIL = dict(
    subject="Your verification code",
    body=(
        "Your one-time verification code is 482931.\n\n"
        "Enter this code to complete your login.\n\n"
        "This code expires in 10 minutes."
    ),
)

_SUPPORT_REQUEST_EMAIL = dict(
    subject="Unable to receive OTP",
    body=(
        "The customer is unable to receive the OTP.\n\n"
        "Please investigate this issue."
    ),
)


async def test_genuine_otp_completes_sla_with_no_rule_engine_configured(monkeypatch):
    sla_service = _FakeSLAService()
    service = _build_service(monkeypatch, sla_service=sla_service, rule_engine_service=None)

    response = await service.receive_email(_email_request(**_GENUINE_OTP_EMAIL))

    assert len(sla_service.completed_calls) == 1
    call = sla_service.completed_calls[0]
    assert call["completion_reason"] == "OTP_RECOGNIZED"
    assert call["interaction_id"] == response.interaction_id or str(call["interaction_id"]) == response.interaction_id


async def test_genuine_otp_completes_sla_before_rule_engine_runs(monkeypatch):
    call_log = []

    class _OrderTrackingSLAService(_FakeSLAService):
        async def complete_first_response_clock(self, **kwargs):
            call_log.append("sla_completed")
            await super().complete_first_response_clock(**kwargs)

    sla_service = _OrderTrackingSLAService()
    rule_engine_service = _FakeRuleEngineService(call_log)

    service = _build_service(monkeypatch, sla_service=sla_service, rule_engine_service=rule_engine_service)

    await service.receive_email(_email_request(**_GENUINE_OTP_EMAIL))

    assert call_log == ["sla_completed", "rule_engine_called"]
    assert len(sla_service.completed_calls) == 1


async def test_otp_forwarding_failure_does_not_prevent_sla_completion(monkeypatch):
    call_log = []
    sla_service = _FakeSLAService()
    rule_engine_service = _FakeRuleEngineService(call_log, raises=True)

    service = _build_service(monkeypatch, sla_service=sla_service, rule_engine_service=rule_engine_service)

    # The rule engine raising is a pre-existing possibility (e.g. a DB
    # error while listing rules) that already propagates today — the
    # point under test is that SLA completion, which now runs first,
    # has already happened by the time that failure occurs.
    try:
        await service.receive_email(_email_request(**_GENUINE_OTP_EMAIL))
    except RuntimeError:
        pass

    assert len(sla_service.completed_calls) == 1
    assert sla_service.completed_calls[0]["completion_reason"] == "OTP_RECOGNIZED"


async def test_support_request_mentioning_otp_does_not_complete_sla(monkeypatch):
    sla_service = _FakeSLAService()
    service = _build_service(monkeypatch, sla_service=sla_service, rule_engine_service=None)

    await service.receive_email(_email_request(**_SUPPORT_REQUEST_EMAIL))

    assert sla_service.completed_calls == []


async def test_normal_email_does_not_complete_sla(monkeypatch):
    sla_service = _FakeSLAService()
    service = _build_service(monkeypatch, sla_service=sla_service, rule_engine_service=None)

    response = await service.receive_email(_email_request())

    assert sla_service.completed_calls == []
    assert response.message == "Email received successfully."

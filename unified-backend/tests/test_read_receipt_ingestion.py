# test_read_receipt_ingestion.py
#
# Ingestion ORDER and failure isolation for inbound read receipts
# (EmailService.receive_email), with the repo's usual minimal fakes (no
# DB): a receipt is consumed BEFORE the duplicate check, the bounce
# branch and any Interaction creation, and nothing it does can ever
# break normal ingestion.
#
# Required order: MDN -> bounce -> normal email.

from uuid import uuid4

import pytest

from app.ticketing.enums import InteractionStatus
from app.ticketing.schemas.email import EmailRequest
from app.ticketing.services import read_receipt_service
from app.ticketing.services.email_service import EmailService
from app.ticketing.services.read_receipt_service import (
    ReadReceiptService,
    ReceiptOutcome,
)
from tests.test_email_service_bounce_handling import (
    _bounce_request,
    _client_request,
    _FakeCategoryRepository,
    _FakeClient,
    _FakeClientRepository,
    _FakeInteractionRepository,
    _FakeNotificationService,
    _FakeUser,
    _FakeUserRepository,
    _NeverCalledRuleEngineService,
    _NeverCalledSLAService,
    _RecordingRuleEngineService,
    _RecordingSLAService,
    _settings,
)


class _ExistsMustNotBeCalledRepository(_FakeInteractionRepository):
    async def exists_by_message_id(self, message_id):
        raise AssertionError(
            "the duplicate check must not run before a read receipt is consumed"
        )


def _receipt_request(**overrides) -> EmailRequest:
    base = dict(
        to_email="ticketing@probeps.com",
        landed_mailbox="ticketing@probeps.com",
        from_email="recipient@example.com",
        subject="Read: Hello",
        body="Your message was read.",
        message_id=f"<{uuid4().hex}@example.com>",
        is_read_receipt=True,
    )
    base.update(overrides)
    return EmailRequest(**base)


def _service(monkeypatch, *, interaction_repository=None, notification_service=None,
             sla_service=None, rule_engine_service=None, user_repository=None,
             client_repository=None):
    monkeypatch.setattr(
        "app.ticketing.services.email_service.get_settings", lambda: _settings()
    )
    return EmailService(
        interaction_repository=interaction_repository or _FakeInteractionRepository(),
        client_repository=client_repository or _FakeClientRepository(),
        attachment_service=None,
        user_repository=user_repository or _FakeUserRepository({}),
        notification_service=notification_service or _FakeNotificationService(),
        sla_service=sla_service or _NeverCalledSLAService(),
        rule_engine_service=rule_engine_service or _NeverCalledRuleEngineService(),
        category_repository=_FakeCategoryRepository(),
    )


def test_receipt_flag_defaults_off_for_every_existing_caller():
    assert EmailRequest(
        to_email="a@example.com", from_email="b@example.com", subject="s",
        body="b", message_id="<x@example.com>",
    ).is_read_receipt is False


async def test_receipt_is_consumed_before_everything_and_creates_nothing(monkeypatch):
    repository = _ExistsMustNotBeCalledRepository()
    notifications = _FakeNotificationService()
    service = _service(
        monkeypatch,
        interaction_repository=repository,
        notification_service=notifications,
        user_repository=_FakeUserRepository({"Site Lead": [_FakeUser(uuid4())]}),
    )

    response = await service.receive_email(_receipt_request())

    # No interaction, ticket, thread, SLA clock (the fake raises if
    # touched), rule run (same) or notification.
    assert repository.created == []
    assert notifications.calls == []
    assert response.status == "READ_RECEIPT"
    assert response.interaction_id == ""
    assert response.ticket_id is None and response.threaded_under is None


async def test_receipt_takes_precedence_over_the_bounce_branch(monkeypatch):
    service = _service(monkeypatch)

    async def _must_not_run(self, email):
        raise AssertionError("a read receipt must never reach the bounce branch")

    monkeypatch.setattr(EmailService, "_receive_bounce", _must_not_run)

    # Even a message BOTH flags claim (e.g. a header-based false bounce
    # positive) is handled as a receipt first.
    response = await service.receive_email(
        _receipt_request(is_bounce=True, from_email="postmaster@example.com")
    )

    assert response.status == "READ_RECEIPT"


async def test_genuine_bounce_is_still_a_bounce(monkeypatch):
    repository = _FakeInteractionRepository()
    service = _service(
        monkeypatch,
        interaction_repository=repository,
        user_repository=_FakeUserRepository({"Site Lead": [_FakeUser(uuid4())]}),
    )

    response = await service.receive_email(_bounce_request())

    assert response.status == InteractionStatus.PENDING.value
    assert len(repository.created) == 1 and repository.created[0].is_bounce is True


async def test_normal_email_is_unaffected_and_still_runs_every_step(monkeypatch):
    client = _FakeClient(uuid4(), "Family First", "familyfirst@probeps.com", uuid4())
    repository = _FakeInteractionRepository()
    rules, sla, notifications = (
        _RecordingRuleEngineService(),
        _RecordingSLAService(),
        _FakeNotificationService(),
    )
    service = _service(
        monkeypatch,
        interaction_repository=repository,
        client_repository=_FakeClientRepository({"familyfirst@probeps.com": client}),
        rule_engine_service=rules,
        sla_service=sla,
        notification_service=notifications,
    )

    await service.receive_email(
        _client_request(
            to_email="familyfirst@probeps.com", landed_mailbox="familyfirst@probeps.com"
        )
    )

    assert rules.calls == 1 and sla.start_first_response_calls == 1
    assert len(repository.created) == 1 and repository.created[0].is_visible is True
    assert notifications.calls[0][1] == "MAIL_RECEIVED"


async def test_feature_flag_off_does_not_stop_receipts_from_being_consumed(monkeypatch):
    # read_receipts_enabled gates REQUESTING receipts, never the
    # protective consume-only branch: a stray receipt must not become a
    # ghost client email just because the UI flag is off. The consume path
    # must not even consult the flag.
    import inspect

    from app.ticketing.services import email_service

    assert "read_receipts_enabled" not in inspect.getsource(email_service)
    assert "read_receipts_enabled" not in inspect.getsource(read_receipt_service)

    service = _service(monkeypatch)
    response = await service.receive_email(_receipt_request())

    assert response.status == "READ_RECEIPT"


# ---------------------------------------------------------------
# Failure isolation — a broken receipt can never break ingestion
# ---------------------------------------------------------------


@pytest.mark.parametrize("boom", [RuntimeError("x"), ValueError("y"), KeyError("z")])
async def test_exception_inside_receipt_processing_is_absorbed(monkeypatch, boom):
    repository = _FakeInteractionRepository()
    client = _FakeClient(uuid4(), "Family First", "familyfirst@probeps.com", uuid4())
    rules, sla = _RecordingRuleEngineService(), _RecordingSLAService()
    service = _service(
        monkeypatch,
        interaction_repository=repository,
        client_repository=_FakeClientRepository({"familyfirst@probeps.com": client}),
        rule_engine_service=rules,
        sla_service=sla,
    )

    async def _explode(self, email):
        raise boom

    monkeypatch.setattr(ReadReceiptService, "_process", _explode)

    # The receipt is consumed, no exception reaches the caller (the
    # poller), and nothing was created.
    response = await service.receive_email(_receipt_request())
    assert response.status == "READ_RECEIPT"
    assert repository.created == []

    # ...and the very next normal email on the same service still works.
    await service.receive_email(
        _client_request(
            to_email="familyfirst@probeps.com", landed_mailbox="familyfirst@probeps.com"
        )
    )
    assert len(repository.created) == 1
    assert rules.calls == 1 and sla.start_first_response_calls == 1


async def test_process_receipt_never_raises_and_logs_no_exception_text(monkeypatch, caplog):
    secret = "patient.name@example.com"

    async def _explode(self, email):
        raise RuntimeError(f"failed for {secret}")

    monkeypatch.setattr(ReadReceiptService, "_process", _explode)
    caplog.set_level("WARNING", logger=read_receipt_service.logger.name)

    outcome = await ReadReceiptService(db=object()).process_receipt(
        _receipt_request(provider_message_id="graph-opaque-id")
    )

    assert outcome is ReceiptOutcome.ERROR
    # Class name only: exception text (which can embed addresses) is
    # never logged.
    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text
    # Subject/body are never logged either.
    assert "Read: Hello" not in caplog.text


async def test_receipt_without_a_fetchable_mime_is_consumed_as_malformed(monkeypatch):
    # No provider_message_id -> nothing to fetch -> consumed, not retried.
    outcome = await ReadReceiptService(db=object()).process_receipt(_receipt_request())
    assert outcome is ReceiptOutcome.MALFORMED

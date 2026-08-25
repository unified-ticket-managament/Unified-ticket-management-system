# test_phase2_inbound_hardening.py
#
# Phase 2 hardening coverage for the inbound-intake edges: the benign
# duplicate-message-id race (item H), Graph subscription failure
# alerting (item I), the unmatched-inbox-address ops notification
# (item J), and the inbound-mail-failure diagnostic record (item K).
# No DB, no real network call — same fakes-only convention as
# test_graph_mail_poller_multi_mailbox.py / test_graph_mail_integration.py.

from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

import app.ticketing.services.graph_mail_poller as graph_mail_poller_module
import app.ticketing.api.mail_integration as mail_integration_module
import app.ticketing.services.graph_subscription_service as graph_subscription_module
from app.core.config import Settings
from app.ticketing.schemas.mail_integration import (
    GraphEmailAddress,
    GraphItemBody,
    GraphRecipient,
    GraphWebhookNotificationItem,
    GraphWebhookResourceData,
    IncomingMailPayload,
)
from app.ticketing.services.mail_integrity import is_duplicate_message_id_violation


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="postgresql+asyncpg://user:pass@localhost/test",
        jwt_secret_key="test-secret",
        sla_sweep_shared_secret="test-sweep-secret",
        graph_tenant_id="tenant-id",
        graph_client_id="client-id",
        graph_client_secret="client-secret",
        graph_mailbox_address="ticketing@probeps.com",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _integrity_error(constraint_name: str | None) -> IntegrityError:
    class _Orig(Exception):
        def __init__(self, name):
            self.constraint_name = name

    return IntegrityError("insert failed", {}, _Orig(constraint_name))


# ---------------------------------------------------------
# mail_integrity.is_duplicate_message_id_violation
# ---------------------------------------------------------


def test_is_duplicate_message_id_violation_true_for_matching_constraint():
    exc = _integrity_error("interactions_message_id_key")
    assert is_duplicate_message_id_violation(exc) is True


def test_is_duplicate_message_id_violation_false_for_unrelated_constraint():
    exc = _integrity_error("tickets_pkey")
    assert is_duplicate_message_id_violation(exc) is False


def test_is_duplicate_message_id_violation_false_for_non_integrity_error():
    assert is_duplicate_message_id_violation(RuntimeError("boom")) is False


# ---------------------------------------------------------
# graph_mail_poller.py — item H (benign race) + item J (unmatched
# inbox) + item K (dead-letter record)
# ---------------------------------------------------------


class _FakeGraphMailProviderClient:
    def __init__(self, messages):
        self._messages = messages

    async def list_new_messages(self, since):
        return self._messages

    async def fetch_message_attachments(self, message_id):
        return []


_FakeGraphMailProviderClient.__name__ = "GraphMailProviderClient"


class _CommittableFakeDBSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _FakeReceivedPayload:
    """
    Doubles as the "mapped EmailRequest" in tests using `_identity_map`
    (map_external_email_to_interaction patched to return its input
    unchanged) — carries from_email/subject too, since the poller's
    item J/K code paths read those off the (normally real EmailRequest)
    `email_request` value.
    """

    def __init__(self, msg_id: str, received_at: datetime):
        self.id = msg_id
        self.internetMessageId = f"<{msg_id}@example.com>"
        self.hasAttachments = False
        self.receivedDateTime = received_at
        self.from_email = "sender@example.com"
        self.subject = "Test subject"

        class body:
            content = ""

        self.body = body


def _identity_map(payload, landed_mailbox=None):
    return payload


def setup_function(function):
    graph_mail_poller_module._state.checkpoints = {}
    graph_mail_poller_module._state.failure_counts = {}


class _RecordingInboundMailFailureRepository:
    """Records calls without touching any real session/DB."""

    instances = []

    def __init__(self, db):
        self.db = db
        self.record_or_increment_calls = []
        self.mark_resolved_calls = []
        _RecordingInboundMailFailureRepository.instances.append(self)

    async def record_or_increment(self, *, message_id, mailbox_address, error_summary):
        self.record_or_increment_calls.append((message_id, mailbox_address, error_summary))

    async def mark_resolved(self, *, message_id, mailbox_address):
        self.mark_resolved_calls.append((message_id, mailbox_address))


class _RecordingNotifyUnmatched:
    def __init__(self):
        self.calls = []

    async def __call__(self, db, *, from_email, subject, mailbox_address):
        self.calls.append((from_email, subject, mailbox_address))


async def test_poll_swallows_benign_duplicate_message_id_race_without_retry_counting(
    monkeypatch, caplog
):
    """
    The losing side of a concurrent-insert race must be logged at info
    and NOT retry-counted/dead-lettered, and must NOT be persisted to
    inbound_mail_failures (a duplicate race is not a genuine failure).
    """

    settings = _settings()
    tick_started_at = datetime.now(timezone.utc)
    payload = _FakeReceivedPayload("dup-msg", tick_started_at - timedelta(minutes=1))

    mail_provider_client = _FakeGraphMailProviderClient(messages=[payload])
    monkeypatch.setattr(
        graph_mail_poller_module,
        "get_mail_provider_client",
        lambda settings, mailbox_address=None: mail_provider_client,
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "map_external_email_to_interaction", _identity_map
    )

    class _RaisesDuplicateEmailService:
        async def receive_email(self, email_request, files=None):
            raise _integrity_error("interactions_message_id_key")

    monkeypatch.setattr(
        graph_mail_poller_module,
        "_build_email_service",
        lambda db: _RaisesDuplicateEmailService(),
    )

    _RecordingInboundMailFailureRepository.instances = []
    monkeypatch.setattr(
        graph_mail_poller_module,
        "InboundMailFailureRepository",
        _RecordingInboundMailFailureRepository,
    )

    mailbox = "dup-race@probeps.com"
    with caplog.at_level("INFO"):
        await graph_mail_poller_module._poll_one_mailbox(settings, mailbox, tick_started_at)

    assert payload.internetMessageId not in graph_mail_poller_module._state.failure_counts.get(
        mailbox, {}
    )
    assert any(
        "lost a concurrent insert race" in record.message for record in caplog.records
    )
    # No genuine-failure diagnostic write for a benign race.
    assert all(
        not repo.record_or_increment_calls
        for repo in _RecordingInboundMailFailureRepository.instances
    )


async def test_poll_still_retries_unrelated_integrity_error(monkeypatch):
    """
    Regression guard: an IntegrityError from an unrelated constraint
    must still be treated as a genuine failure — retry-counted exactly
    like any other exception, not swallowed as a benign race.
    """

    settings = _settings()
    tick_started_at = datetime.now(timezone.utc)
    payload = _FakeReceivedPayload("other-constraint-msg", tick_started_at - timedelta(minutes=1))

    mail_provider_client = _FakeGraphMailProviderClient(messages=[payload])
    monkeypatch.setattr(
        graph_mail_poller_module,
        "get_mail_provider_client",
        lambda settings, mailbox_address=None: mail_provider_client,
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "map_external_email_to_interaction", _identity_map
    )

    class _RaisesUnrelatedIntegrityError:
        async def receive_email(self, email_request, files=None):
            raise _integrity_error("tickets_pkey")

    monkeypatch.setattr(
        graph_mail_poller_module,
        "_build_email_service",
        lambda db: _RaisesUnrelatedIntegrityError(),
    )

    recorded = []

    class _Repo:
        def __init__(self, db):
            pass

        async def record_or_increment(self, *, message_id, mailbox_address, error_summary):
            recorded.append((message_id, mailbox_address))

        async def mark_resolved(self, *, message_id, mailbox_address):
            pass

    monkeypatch.setattr(graph_mail_poller_module, "InboundMailFailureRepository", _Repo)

    mailbox = "unrelated-constraint@probeps.com"
    await graph_mail_poller_module._poll_one_mailbox(settings, mailbox, tick_started_at)

    assert (
        graph_mail_poller_module._state.failure_counts[mailbox][payload.internetMessageId] == 1
    )
    assert recorded == [(payload.internetMessageId, mailbox)]


async def test_poll_unknown_inbox_address_warns_and_notifies_without_retry(monkeypatch, caplog):
    settings = _settings()
    tick_started_at = datetime.now(timezone.utc)
    payload = _FakeReceivedPayload("unmatched-msg", tick_started_at - timedelta(minutes=1))

    mail_provider_client = _FakeGraphMailProviderClient(messages=[payload])
    monkeypatch.setattr(
        graph_mail_poller_module,
        "get_mail_provider_client",
        lambda settings, mailbox_address=None: mail_provider_client,
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "map_external_email_to_interaction", _identity_map
    )

    class _RaisesUnknownInbox:
        async def receive_email(self, email_request, files=None):
            raise ValueError("Unknown inbox address.")

    monkeypatch.setattr(
        graph_mail_poller_module, "_build_email_service", lambda db: _RaisesUnknownInbox()
    )

    notify_spy = _RecordingNotifyUnmatched()
    monkeypatch.setattr(graph_mail_poller_module, "notify_unmatched_inbox_email", notify_spy)

    mailbox = "unmapped@probeps.com"
    with caplog.at_level("INFO"):
        await graph_mail_poller_module._poll_one_mailbox(settings, mailbox, tick_started_at)

    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("unmapped inbox address" in r.message for r in warning_records)
    assert len(notify_spy.calls) == 1
    assert notify_spy.calls[0][2] == mailbox
    # Terminal, non-retryable outcome — never counted as a failure.
    assert payload.internetMessageId not in graph_mail_poller_module._state.failure_counts.get(
        mailbox, {}
    )


async def test_poll_already_processed_unaffected_by_unmatched_inbox_change(monkeypatch, caplog):
    """Regression guard: 'Email already processed.' must stay info-only
    with no notification call — only 'Unknown inbox address.' changed."""

    settings = _settings()
    tick_started_at = datetime.now(timezone.utc)
    payload = _FakeReceivedPayload("already-processed-msg", tick_started_at - timedelta(minutes=1))

    mail_provider_client = _FakeGraphMailProviderClient(messages=[payload])
    monkeypatch.setattr(
        graph_mail_poller_module,
        "get_mail_provider_client",
        lambda settings, mailbox_address=None: mail_provider_client,
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "map_external_email_to_interaction", _identity_map
    )

    class _RaisesAlreadyProcessed:
        async def receive_email(self, email_request, files=None):
            raise ValueError("Email already processed.")

    monkeypatch.setattr(
        graph_mail_poller_module, "_build_email_service", lambda db: _RaisesAlreadyProcessed()
    )

    notify_spy = _RecordingNotifyUnmatched()
    monkeypatch.setattr(graph_mail_poller_module, "notify_unmatched_inbox_email", notify_spy)

    mailbox = "already-processed@probeps.com"
    with caplog.at_level("INFO"):
        await graph_mail_poller_module._poll_one_mailbox(settings, mailbox, tick_started_at)

    assert not notify_spy.calls
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert not any("unmapped inbox address" in r.message for r in warning_records)


async def test_poll_success_marks_prior_failure_resolved(monkeypatch):
    settings = _settings()
    tick_started_at = datetime.now(timezone.utc)
    payload = _FakeReceivedPayload("recovers-msg", tick_started_at - timedelta(minutes=1))

    mail_provider_client = _FakeGraphMailProviderClient(messages=[payload])
    monkeypatch.setattr(
        graph_mail_poller_module,
        "get_mail_provider_client",
        lambda settings, mailbox_address=None: mail_provider_client,
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "map_external_email_to_interaction", _identity_map
    )

    class _SucceedsEmailService:
        async def receive_email(self, email_request, files=None):
            class _Response:
                pass

            return _Response()

    monkeypatch.setattr(
        graph_mail_poller_module, "_build_email_service", lambda db: _SucceedsEmailService()
    )

    resolved_calls = []

    class _Repo:
        def __init__(self, db):
            pass

        async def record_or_increment(self, *, message_id, mailbox_address, error_summary):
            pass

        async def mark_resolved(self, *, message_id, mailbox_address):
            resolved_calls.append((message_id, mailbox_address))

    monkeypatch.setattr(graph_mail_poller_module, "InboundMailFailureRepository", _Repo)

    mailbox = "recovers@probeps.com"
    await graph_mail_poller_module._poll_one_mailbox(settings, mailbox, tick_started_at)

    assert resolved_calls == [(payload.internetMessageId, mailbox)]


# ---------------------------------------------------------
# mail_integration.py's _process_graph_notification — items H/J/K,
# webhook side
# ---------------------------------------------------------


def _webhook_payload() -> IncomingMailPayload:
    return IncomingMailPayload(
        internetMessageId="<webhook-msg@example.com>",
        subject="hello",
        from_=GraphRecipient(emailAddress=GraphEmailAddress(address="sender@example.com")),
        toRecipients=[
            GraphRecipient(emailAddress=GraphEmailAddress(address="ticketing@probeps.com"))
        ],
        body=GraphItemBody(contentType="text", content="hi"),
    )


def _webhook_item() -> GraphWebhookNotificationItem:
    return GraphWebhookNotificationItem(
        subscriptionId="sub-1",
        clientState="secret",
        changeType="created",
        resource="/users/ticketing@probeps.com/messages/abc",
        resourceData=GraphWebhookResourceData(id="abc"),
    )


class _FakeMailProviderClient:
    def __init__(self, payload):
        self._payload = payload

    async def fetch_message(self, message_id):
        return self._payload


def _wire_webhook_common(monkeypatch, settings, email_service):
    monkeypatch.setattr(mail_integration_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        mail_integration_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
    )
    monkeypatch.setattr(mail_integration_module, "_build_email_service", lambda db: email_service)


async def test_webhook_swallows_benign_duplicate_message_id_race(monkeypatch, caplog):
    settings = _settings(graph_webhook_client_state="secret")

    class _RaisesDuplicate:
        async def receive_email(self, email_request, files=None):
            raise _integrity_error("interactions_message_id_key")

    _wire_webhook_common(monkeypatch, settings, _RaisesDuplicate())

    recorded = []

    class _Repo:
        def __init__(self, db):
            pass

        async def record_or_increment(self, *, message_id, mailbox_address, error_summary):
            recorded.append((message_id, mailbox_address))

        async def mark_resolved(self, *, message_id, mailbox_address):
            pass

    monkeypatch.setattr(mail_integration_module, "InboundMailFailureRepository", _Repo)

    with caplog.at_level("INFO"):
        await mail_integration_module._process_graph_notification(
            _webhook_item(), _FakeMailProviderClient(_webhook_payload())
        )

    assert any("lost a concurrent insert race" in r.message for r in caplog.records)
    assert recorded == []


async def test_webhook_still_records_unrelated_integrity_error(monkeypatch):
    settings = _settings(graph_webhook_client_state="secret")

    class _RaisesUnrelated:
        async def receive_email(self, email_request, files=None):
            raise _integrity_error("tickets_pkey")

    _wire_webhook_common(monkeypatch, settings, _RaisesUnrelated())

    recorded = []

    class _Repo:
        def __init__(self, db):
            pass

        async def record_or_increment(self, *, message_id, mailbox_address, error_summary):
            recorded.append((message_id, mailbox_address))

        async def mark_resolved(self, *, message_id, mailbox_address):
            pass

    monkeypatch.setattr(mail_integration_module, "InboundMailFailureRepository", _Repo)

    await mail_integration_module._process_graph_notification(
        _webhook_item(), _FakeMailProviderClient(_webhook_payload())
    )

    assert len(recorded) == 1
    assert recorded[0][0] == "<webhook-msg@example.com>"


async def test_webhook_unknown_inbox_address_warns_and_notifies(monkeypatch, caplog):
    settings = _settings(graph_webhook_client_state="secret")

    class _RaisesUnknownInbox:
        async def receive_email(self, email_request, files=None):
            raise ValueError("Unknown inbox address.")

    _wire_webhook_common(monkeypatch, settings, _RaisesUnknownInbox())

    notify_spy = _RecordingNotifyUnmatched()
    monkeypatch.setattr(mail_integration_module, "notify_unmatched_inbox_email", notify_spy)

    with caplog.at_level("INFO"):
        await mail_integration_module._process_graph_notification(
            _webhook_item(), _FakeMailProviderClient(_webhook_payload())
        )

    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("unmapped inbox address" in r.message for r in warning_records)
    assert len(notify_spy.calls) == 1


async def test_webhook_already_processed_unaffected(monkeypatch, caplog):
    settings = _settings(graph_webhook_client_state="secret")

    class _RaisesAlreadyProcessed:
        async def receive_email(self, email_request, files=None):
            raise ValueError("Email already processed.")

    _wire_webhook_common(monkeypatch, settings, _RaisesAlreadyProcessed())

    notify_spy = _RecordingNotifyUnmatched()
    monkeypatch.setattr(mail_integration_module, "notify_unmatched_inbox_email", notify_spy)

    with caplog.at_level("INFO"):
        await mail_integration_module._process_graph_notification(
            _webhook_item(), _FakeMailProviderClient(_webhook_payload())
        )

    assert not notify_spy.calls


async def test_webhook_success_marks_prior_failure_resolved(monkeypatch):
    settings = _settings(graph_webhook_client_state="secret")

    class _Succeeds:
        async def receive_email(self, email_request, files=None):
            return None

    _wire_webhook_common(monkeypatch, settings, _Succeeds())

    resolved_calls = []

    class _Repo:
        def __init__(self, db):
            pass

        async def record_or_increment(self, *, message_id, mailbox_address, error_summary):
            pass

        async def mark_resolved(self, *, message_id, mailbox_address):
            resolved_calls.append((message_id, mailbox_address))

    monkeypatch.setattr(mail_integration_module, "InboundMailFailureRepository", _Repo)

    await mail_integration_module._process_graph_notification(
        _webhook_item(), _FakeMailProviderClient(_webhook_payload())
    )

    assert resolved_calls == [("<webhook-msg@example.com>", "ticketing@probeps.com")]


# ---------------------------------------------------------
# graph_subscription_service.py — item I (subscription failure alerting)
# ---------------------------------------------------------


class _FakeHttpResponse:
    def __init__(self, status_code, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


async def test_subscription_creation_failure_notifies_ops(monkeypatch):
    settings = _settings(
        graph_webhook_client_state="secret",
        graph_webhook_notification_url="https://example.com/webhook",
    )

    async def _fake_call_with_graph_retry(attempt, *, operation, force_refresh_token, **kwargs):
        return _FakeHttpResponse(400, text="bad request")

    monkeypatch.setattr(
        graph_subscription_module, "call_with_graph_retry", _fake_call_with_graph_retry
    )

    class _FakeAuthClient:
        async def get_token(self, force_refresh=False):
            return "token"

    notify_calls = []

    async def _fake_notify(*, action, status_code, detail):
        notify_calls.append((action, status_code, detail))

    monkeypatch.setattr(
        graph_subscription_module, "_notify_ops_of_subscription_failure", _fake_notify
    )

    await graph_subscription_module._create(
        settings, _FakeAuthClient(), datetime.now(timezone.utc)
    )

    assert notify_calls == [("creation", 400, "bad request")]


async def test_subscription_renewal_failure_notifies_ops(monkeypatch):
    settings = _settings(graph_webhook_client_state="secret")
    graph_subscription_module._state.subscription_id = "sub-1"
    graph_subscription_module._state.expires_at = datetime.now(timezone.utc)

    async def _fake_call_with_graph_retry(attempt, *, operation, force_refresh_token, **kwargs):
        return _FakeHttpResponse(500, text="server error")

    monkeypatch.setattr(
        graph_subscription_module, "call_with_graph_retry", _fake_call_with_graph_retry
    )

    class _FakeAuthClient:
        async def get_token(self, force_refresh=False):
            return "token"

    notify_calls = []

    async def _fake_notify(*, action, status_code, detail):
        notify_calls.append((action, status_code, detail))

    monkeypatch.setattr(
        graph_subscription_module, "_notify_ops_of_subscription_failure", _fake_notify
    )

    await graph_subscription_module._renew(
        settings, _FakeAuthClient(), datetime.now(timezone.utc)
    )

    assert notify_calls == [("renewal", 500, "server error")]
    # Stale id/expiry forgotten so next tick creates a fresh subscription.
    assert graph_subscription_module._state.subscription_id is None
    assert graph_subscription_module._state.expires_at is None


async def test_notify_ops_of_subscription_failure_never_raises_on_internal_error(monkeypatch):
    """
    A failure inside the notify helper itself (e.g. a DB error resolving
    recipients) must never propagate out and mask/crash the original
    creation/renewal failure path calling it.
    """

    class _BoomSessionLocal:
        def __call__(self):
            raise RuntimeError("DB unavailable")

    monkeypatch.setattr(
        "app.database.session.AsyncSessionLocal", _BoomSessionLocal(), raising=False
    )

    # Should not raise.
    await graph_subscription_module._notify_ops_of_subscription_failure(
        action="creation", status_code=500, detail="boom"
    )


# ---------------------------------------------------------
# GET /api/mail/inbound-failures — item K's read-only ops endpoint,
# permission-gating (Site Lead/Super Admin unrestricted, else requires
# ticket:view_global_audit_log)
# ---------------------------------------------------------


class _FakeRole:
    def __init__(self, name):
        self.name = name


class _FakeCurrentUser:
    def __init__(self, role_name, permissions=None):
        self.role = _FakeRole(role_name)
        self.permissions = permissions or []


class _FakeInboundFailureRepoForEndpoint:
    def __init__(self, db):
        pass

    async def list_unresolved(self, *, limit, offset):
        return [], 0


async def test_inbound_failures_endpoint_site_lead_unrestricted(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(
        mail_integration_module,
        "InboundMailFailureRepository",
        _FakeInboundFailureRepoForEndpoint,
    )

    response = await mail_integration_module.list_inbound_mail_failures(
        limit=50,
        offset=0,
        current_user=_FakeCurrentUser("Site Lead"),
        db=None,
    )
    assert response.total == 0
    assert response.items == []


async def test_inbound_failures_endpoint_forbidden_without_permission(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(
        mail_integration_module,
        "InboundMailFailureRepository",
        _FakeInboundFailureRepoForEndpoint,
    )

    raised = None
    try:
        await mail_integration_module.list_inbound_mail_failures(
            limit=50,
            offset=0,
            current_user=_FakeCurrentUser("Staff", permissions=[]),
            db=None,
        )
    except HTTPException as exc:
        raised = exc

    assert raised is not None
    assert raised.status_code == 403


async def test_inbound_failures_endpoint_allowed_with_permission(monkeypatch):
    monkeypatch.setattr(
        mail_integration_module,
        "InboundMailFailureRepository",
        _FakeInboundFailureRepoForEndpoint,
    )

    response = await mail_integration_module.list_inbound_mail_failures(
        limit=50,
        offset=0,
        current_user=_FakeCurrentUser(
            "Staff", permissions=["ticket:view_global_audit_log"]
        ),
        db=None,
    )
    assert response.total == 0

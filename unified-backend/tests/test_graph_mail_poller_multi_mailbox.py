# test_graph_mail_poller_multi_mailbox.py
#
# Pure-logic coverage for the multi-mailbox poller restructure
# (graph_mail_poller.py) — no DB, no real network call. Verifies:
# mailbox enumeration (shared mailbox + every active client's own
# inbox_email, deduped), per-mailbox checkpoint independence, and that
# one mailbox's failure (e.g. a client mailbox not yet granted Graph
# app access) never stops another mailbox's tick.

from datetime import datetime, timedelta, timezone

from app.core.config import Settings
import app.ticketing.services.graph_mail_poller as graph_mail_poller_module


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


class _FakeDBSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeClientRepository:
    def __init__(self, db, inbox_emails=None):
        self._inbox_emails = inbox_emails or []

    async def list_active_inbox_emails(self):
        return self._inbox_emails


def setup_function(function):
    # Fresh per-mailbox checkpoint state for every test — this module
    # state is otherwise shared/mutated across the whole test process.
    graph_mail_poller_module._state.checkpoints = {}


async def test_resolve_mailboxes_to_poll_includes_shared_and_client_mailboxes(monkeypatch):
    settings = _settings()

    monkeypatch.setattr(graph_mail_poller_module, "AsyncSessionLocal", lambda: _FakeDBSession())
    monkeypatch.setattr(
        graph_mail_poller_module,
        "ClientRepository",
        lambda db: _FakeClientRepository(
            db, inbox_emails=["FamilyFirst@Probeps.com", "apm@probeps.com"]
        ),
    )

    mailboxes = await graph_mail_poller_module._resolve_mailboxes_to_poll(settings)

    assert set(mailboxes) == {
        "ticketing@probeps.com",
        "familyfirst@probeps.com",
        "apm@probeps.com",
    }


async def test_resolve_mailboxes_to_poll_dedupes_when_client_matches_shared_mailbox(monkeypatch):
    settings = _settings(graph_mailbox_address="shared@probeps.com")

    monkeypatch.setattr(graph_mail_poller_module, "AsyncSessionLocal", lambda: _FakeDBSession())
    monkeypatch.setattr(
        graph_mail_poller_module,
        "ClientRepository",
        lambda db: _FakeClientRepository(db, inbox_emails=["shared@probeps.com", "apm@probeps.com"]),
    )

    mailboxes = await graph_mail_poller_module._resolve_mailboxes_to_poll(settings)

    assert set(mailboxes) == {"shared@probeps.com", "apm@probeps.com"}


class _FakeGraphMailProviderClient:
    """Named to match the real class only via __class__.__name__ patch
    below — _poll_one_mailbox defensively checks that name before
    proceeding."""

    def __init__(self, messages=None, should_raise_status=None):
        self._messages = messages or []
        self._should_raise_status = should_raise_status

    async def list_new_messages(self, since):
        if self._should_raise_status is not None:
            raise graph_mail_poller_module.GraphAPIError(
                self._should_raise_status, "not authorized yet"
            )
        return self._messages

    async def fetch_message_attachments(self, message_id):
        return []


_FakeGraphMailProviderClient.__name__ = "GraphMailProviderClient"


async def test_one_mailbox_failure_does_not_block_another_mailboxs_tick(monkeypatch):
    """
    The core rollout-safety guarantee: a client mailbox not yet
    granted Graph app access (403/404, modeled here as a
    GraphAPIError) must not prevent the shared mailbox — or any other
    client mailbox — from being polled in the same tick.
    """

    settings = _settings()

    async def _fake_resolve_mailboxes(settings):
        return ["ticketing@probeps.com", "familyfirst@probeps.com", "notyetauthorized@probeps.com"]

    clients_by_mailbox = {
        "ticketing@probeps.com": _FakeGraphMailProviderClient(messages=[]),
        "familyfirst@probeps.com": _FakeGraphMailProviderClient(messages=[]),
        "notyetauthorized@probeps.com": _FakeGraphMailProviderClient(should_raise_status=403),
    }

    def _fake_get_mail_provider_client(settings, mailbox_address=None):
        return clients_by_mailbox[mailbox_address]

    monkeypatch.setattr(
        graph_mail_poller_module, "_resolve_mailboxes_to_poll", _fake_resolve_mailboxes
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "get_mail_provider_client", _fake_get_mail_provider_client
    )

    # Should not raise, despite one mailbox failing.
    await graph_mail_poller_module.poll_new_messages(settings)

    # The two reachable mailboxes advanced their checkpoint; the
    # unauthorized one did not (so it retries next tick).
    assert "ticketing@probeps.com" in graph_mail_poller_module._state.checkpoints
    assert "familyfirst@probeps.com" in graph_mail_poller_module._state.checkpoints
    assert "notyetauthorized@probeps.com" not in graph_mail_poller_module._state.checkpoints


async def test_per_mailbox_checkpoints_are_independent(monkeypatch):
    settings = _settings()

    stale_checkpoint = datetime.now(timezone.utc) - timedelta(hours=1)
    graph_mail_poller_module._state.checkpoints["ticketing@probeps.com"] = stale_checkpoint

    async def _fake_resolve_mailboxes(settings):
        return ["ticketing@probeps.com", "familyfirst@probeps.com"]

    clients_by_mailbox = {
        "ticketing@probeps.com": _FakeGraphMailProviderClient(messages=[]),
        "familyfirst@probeps.com": _FakeGraphMailProviderClient(messages=[]),
    }

    def _fake_get_mail_provider_client(settings, mailbox_address=None):
        return clients_by_mailbox[mailbox_address]

    monkeypatch.setattr(
        graph_mail_poller_module, "_resolve_mailboxes_to_poll", _fake_resolve_mailboxes
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "get_mail_provider_client", _fake_get_mail_provider_client
    )

    await graph_mail_poller_module.poll_new_messages(settings)

    # Both mailboxes now have their own, independently-advanced
    # checkpoint — ticketing@'s pre-existing stale checkpoint didn't
    # leak into or block familyfirst@'s first-ever poll.
    assert (
        graph_mail_poller_module._state.checkpoints["ticketing@probeps.com"]
        > stale_checkpoint
    )
    assert "familyfirst@probeps.com" in graph_mail_poller_module._state.checkpoints


class _CommittableFakeDBSession(_FakeDBSession):
    async def commit(self):
        pass

    async def rollback(self):
        pass


class _FakePayload:
    """
    A minimal IncomingMailPayload stand-in whose own to/cc fields (had
    map_external_email_to_interaction actually run against it) would
    say nothing about which mailbox this landed in — mirroring a real
    Bcc delivery, where the only way to know which configured mailbox
    received the message is which mailbox's Inbox Graph returned it
    from in the first place.
    """

    id = "msg-1"
    internetMessageId = "<msg-1@example.com>"
    hasAttachments = False

    class body:
        content = ""


async def test_poll_one_mailbox_threads_mailbox_address_into_email_mapping(monkeypatch):
    """
    The poller-level half of the landed_mailbox fix (see
    test_email_service_client_matching.py for the service-level
    resolution logic this feeds): _poll_one_mailbox must pass the
    mailbox it actually polled into map_external_email_to_interaction
    as `landed_mailbox`, not just fetch messages and forget which
    mailbox they came from. Spies on map_external_email_to_interaction
    itself (rather than re-mocking EmailService.receive_email away
    entirely) so this test fails if a future edit ever drops the
    landed_mailbox= keyword from that call site.
    """

    settings = _settings()
    mail_provider_client = _FakeGraphMailProviderClient(messages=[_FakePayload()])

    monkeypatch.setattr(
        graph_mail_poller_module,
        "get_mail_provider_client",
        lambda settings, mailbox_address=None: mail_provider_client,
    )
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
    )

    class _FakeEmailService:
        async def receive_email(self, email_request, files=None):
            class _Response:
                pass

            return _Response()

    monkeypatch.setattr(
        graph_mail_poller_module, "_build_email_service", lambda db: _FakeEmailService()
    )

    # Spies on the call rather than invoking the real mapping function
    # — _FakePayload above deliberately only carries the handful of
    # attributes _poll_one_mailbox itself reads (id/internetMessageId/
    # hasAttachments/body.content), not the full IncomingMailPayload
    # shape map_external_email_to_interaction would need; the fake
    # EmailService above doesn't care what the resulting "EmailRequest"
    # actually is.
    calls = []

    def _spying_map(payload, landed_mailbox=None):
        calls.append(landed_mailbox)
        return object()

    monkeypatch.setattr(
        graph_mail_poller_module, "map_external_email_to_interaction", _spying_map
    )

    await graph_mail_poller_module._poll_one_mailbox(
        settings, "credentialing@probeps.com", datetime.now(timezone.utc)
    )

    assert calls == ["credentialing@probeps.com"]

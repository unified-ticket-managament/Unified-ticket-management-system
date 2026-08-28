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


class _FakeCategoryRepository:
    def __init__(self, db, inbox_emails=None):
        self._inbox_emails = inbox_emails or []

    async def list_active_inbox_emails(self):
        return self._inbox_emails


def setup_function(function):
    # Fresh per-mailbox checkpoint/failure-count state for every test —
    # this module state is otherwise shared/mutated across the whole
    # test process. checkpoints_seeded reset too, so
    # poll_new_messages's one-time persisted-checkpoint seed is
    # exercised (and must be safely no-op'd via a mocked
    # AsyncSessionLocal, never a real DB touch) by every test that
    # calls it, not just whichever happens to run first in the module.
    graph_mail_poller_module._state.checkpoints = {}
    graph_mail_poller_module._state.failure_counts = {}
    graph_mail_poller_module._state.checkpoints_seeded = False


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
    monkeypatch.setattr(
        graph_mail_poller_module,
        "CategoryRepository",
        lambda db: _FakeCategoryRepository(db, inbox_emails=[]),
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
    monkeypatch.setattr(
        graph_mail_poller_module,
        "CategoryRepository",
        lambda db: _FakeCategoryRepository(db, inbox_emails=[]),
    )

    mailboxes = await graph_mail_poller_module._resolve_mailboxes_to_poll(settings)

    assert set(mailboxes) == {"shared@probeps.com", "apm@probeps.com"}


async def test_resolve_mailboxes_to_poll_includes_category_mailboxes(monkeypatch):
    """
    New behavior: an active category's own inbox_email (e.g.
    apm@probeps.com, mapped to the APM category rather than any
    client) is unioned into the poll set alongside the shared mailbox
    and every client's own inbox_email.
    """

    settings = _settings()

    monkeypatch.setattr(graph_mail_poller_module, "AsyncSessionLocal", lambda: _FakeDBSession())
    monkeypatch.setattr(
        graph_mail_poller_module,
        "ClientRepository",
        lambda db: _FakeClientRepository(db, inbox_emails=["familyfirst@probeps.com"]),
    )
    monkeypatch.setattr(
        graph_mail_poller_module,
        "CategoryRepository",
        lambda db: _FakeCategoryRepository(
            db, inbox_emails=["APM@Probeps.com", "patientoutreach@probeps.com"]
        ),
    )

    mailboxes = await graph_mail_poller_module._resolve_mailboxes_to_poll(settings)

    assert set(mailboxes) == {
        "ticketing@probeps.com",
        "familyfirst@probeps.com",
        "apm@probeps.com",
        "patientoutreach@probeps.com",
    }


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
    # Keeps this a pure-logic test per the module docstring — without
    # this, the GraphAPIError branch's mailbox-stall bookkeeping
    # (MailboxPollStateRepository.record_failure) would open a real
    # AsyncSessionLocal() against the live DB.
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
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
    # Keeps this a pure-logic test per the module docstring — see the
    # identical comment in test_one_mailbox_failure_does_not_block_
    # another_mailboxs_tick above.
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
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


class _FakeReceivedPayload:
    """
    A minimal IncomingMailPayload stand-in carrying exactly the
    attributes _poll_one_mailbox's retry/checkpoint logic reads:
    id/internetMessageId (message identity) and receivedDateTime
    (which message a held-back checkpoint must not advance past).
    map_external_email_to_interaction is monkeypatched to the identity
    function in the tests below, so the "email_request" _build_email_
    service's receive_email sees is this same object.
    """

    def __init__(self, msg_id: str, received_at: datetime):
        self.id = msg_id
        self.internetMessageId = f"<{msg_id}@example.com>"
        self.hasAttachments = False
        self.receivedDateTime = received_at

        class body:
            content = ""

        self.body = body


def _identity_map(payload, landed_mailbox=None):
    return payload


async def test_poll_holds_checkpoint_back_to_a_failed_messages_own_time(monkeypatch):
    """
    The core fix: a message that fails with a genuine (non-ValueError)
    exception must not be silently skipped forever. The checkpoint
    must be held back to just before that message's own arrival time —
    not advanced to when this tick started — so the next tick's
    `receivedDateTime gt since` filter re-includes it.
    """

    settings = _settings()
    tick_started_at = datetime.now(timezone.utc)
    ok_time = tick_started_at - timedelta(minutes=10)
    fail_time = tick_started_at - timedelta(minutes=5)

    ok_payload = _FakeReceivedPayload("ok-msg", ok_time)
    fail_payload = _FakeReceivedPayload("fail-msg", fail_time)

    mail_provider_client = _FakeGraphMailProviderClient(messages=[ok_payload, fail_payload])
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

    class _PartiallyFailingEmailService:
        async def receive_email(self, email_request, files=None):
            if email_request.id == "fail-msg":
                raise RuntimeError("simulated transient failure")

            class _Response:
                pass

            return _Response()

    monkeypatch.setattr(
        graph_mail_poller_module, "_build_email_service", lambda db: _PartiallyFailingEmailService()
    )

    mailbox = "holdback@probeps.com"
    await graph_mail_poller_module._poll_one_mailbox(settings, mailbox, tick_started_at)

    checkpoint = graph_mail_poller_module._state.checkpoints[mailbox]
    # Held back to just before the failed message's own time...
    assert checkpoint < fail_time
    # ...specifically at (fail_time - 1 microsecond), not merely
    # "somewhere earlier" — the exact boundary that makes the next
    # tick's `receivedDateTime gt since` filter re-include it.
    assert checkpoint == fail_time - timedelta(microseconds=1)
    # Never advanced all the way to when this tick started, unlike
    # the pre-fix behavior.
    assert checkpoint != tick_started_at


async def test_poll_dead_letters_a_message_after_max_retries(monkeypatch):
    """
    A message failing MAX_MESSAGE_RETRY_ATTEMPTS consecutive times
    (across that many separate poll ticks) is dead-lettered: logged
    distinctly and no longer holding the checkpoint back — a single
    permanently-broken message must not block every other message
    behind it forever.
    """

    settings = _settings()
    tick_started_at = datetime.now(timezone.utc)
    fail_time = tick_started_at - timedelta(minutes=5)
    payload = _FakeReceivedPayload("always-fails", fail_time)

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

    class _AlwaysFailingEmailService:
        async def receive_email(self, email_request, files=None):
            raise RuntimeError("simulated permanent failure")

    monkeypatch.setattr(
        graph_mail_poller_module, "_build_email_service", lambda db: _AlwaysFailingEmailService()
    )

    mailbox = "deadletter@probeps.com"

    for attempt in range(1, graph_mail_poller_module.MAX_MESSAGE_RETRY_ATTEMPTS):
        await graph_mail_poller_module._poll_one_mailbox(settings, mailbox, tick_started_at)
        # Still short of the retry ceiling — checkpoint stays held
        # back at this message's own time on every attempt so far.
        assert graph_mail_poller_module._state.checkpoints[mailbox] == (
            fail_time - timedelta(microseconds=1)
        )
        assert (
            graph_mail_poller_module._state.failure_counts[mailbox][payload.internetMessageId]
            == attempt
        )

    # The MAX_MESSAGE_RETRY_ATTEMPTS-th failure dead-letters it.
    await graph_mail_poller_module._poll_one_mailbox(settings, mailbox, tick_started_at)

    assert payload.internetMessageId not in graph_mail_poller_module._state.failure_counts.get(
        mailbox, {}
    )
    # Free to advance all the way to this tick's start time now that
    # nothing is still holding it back.
    assert graph_mail_poller_module._state.checkpoints[mailbox] == tick_started_at


async def test_poll_clears_failure_count_once_a_previously_failing_message_succeeds(monkeypatch):
    """
    A message that failed on an earlier tick and then succeeds on a
    later one must have its retry count forgotten — otherwise a
    transient failure long ago could contribute toward prematurely
    dead-lettering a message that's actually fine now.
    """

    settings = _settings()
    tick_started_at = datetime.now(timezone.utc)
    fail_time = tick_started_at - timedelta(minutes=5)
    mailbox = "recovers@probeps.com"

    payload = _FakeReceivedPayload("eventually-succeeds", fail_time)
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

    class _FailsOnceThenSucceeds:
        def __init__(self):
            self.calls = 0

        async def receive_email(self, email_request, files=None):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated transient failure")

            class _Response:
                pass

            return _Response()

    service = _FailsOnceThenSucceeds()
    monkeypatch.setattr(graph_mail_poller_module, "_build_email_service", lambda db: service)

    # First tick: fails, checkpoint held back, failure count recorded.
    await graph_mail_poller_module._poll_one_mailbox(settings, mailbox, tick_started_at)
    assert graph_mail_poller_module._state.failure_counts[mailbox][payload.internetMessageId] == 1

    # Second tick: succeeds — failure count forgotten, checkpoint free
    # to advance normally.
    await graph_mail_poller_module._poll_one_mailbox(settings, mailbox, tick_started_at)
    assert payload.internetMessageId not in graph_mail_poller_module._state.failure_counts.get(
        mailbox, {}
    )
    assert graph_mail_poller_module._state.checkpoints[mailbox] == tick_started_at


# ---------------------------------------------------------------
# Persisted-checkpoint seeding (Fix 2) and mailbox-stall alerting
# (Fix 3) — the mail-ingestion-reliability fix on top of the
# already-covered per-message retry/dead-letter logic above.
# ---------------------------------------------------------------


class _FakeMailboxPollState:
    def __init__(
        self,
        consecutive_failures=0,
        last_success_at=None,
        last_alerted_at=None,
    ):
        self.consecutive_failures = consecutive_failures
        self.last_success_at = last_success_at
        self.last_alerted_at = last_alerted_at


class _FakeMailboxPollStateRepository:
    """Shared, in-memory stand-in for MailboxPollStateRepository —
    same instance handed back for every `MailboxPollStateRepository(db)`
    construction within a test (see the factory below), so state
    written by one call is visible to the next, exactly like the real
    upsert-backed table would be within one process."""

    def __init__(self, checkpoints=None, states=None):
        self.checkpoints = dict(checkpoints or {})
        self.states = dict(states or {})
        self.record_success_calls = []
        self.record_failure_calls = []
        self.mark_alerted_calls = []

    def __call__(self, db):
        return self

    async def get_all_checkpoints(self):
        return dict(self.checkpoints)

    async def record_success(self, *, mailbox_address, checkpoint_at):
        self.record_success_calls.append((mailbox_address, checkpoint_at))
        self.checkpoints[mailbox_address] = checkpoint_at
        self.states[mailbox_address] = _FakeMailboxPollState(
            consecutive_failures=0,
            last_success_at=checkpoint_at,
            last_alerted_at=self.states.get(mailbox_address)
            and self.states[mailbox_address].last_alerted_at,
        )

    async def record_failure(self, *, mailbox_address, error_summary):
        self.record_failure_calls.append((mailbox_address, error_summary))
        existing = self.states.get(mailbox_address)
        new_count = (existing.consecutive_failures if existing else 0) + 1
        self.states[mailbox_address] = _FakeMailboxPollState(
            consecutive_failures=new_count,
            last_success_at=existing.last_success_at if existing else None,
            last_alerted_at=existing.last_alerted_at if existing else None,
        )
        return new_count

    async def mark_alerted(self, *, mailbox_address):
        self.mark_alerted_calls.append(mailbox_address)
        state = self.states[mailbox_address]
        state.last_alerted_at = datetime.now(timezone.utc)

    async def get(self, *, mailbox_address):
        return self.states.get(mailbox_address)


async def test_poll_new_messages_seeds_checkpoint_from_persisted_state(monkeypatch):
    """
    Fix 2: a fresh process (empty _state.checkpoints, as after a
    restart) must resume from the persisted mailbox_poll_state
    checkpoint rather than always falling back to
    INITIAL_LOOKBACK_MINUTES.
    """

    settings = _settings()
    persisted_checkpoint = datetime.now(timezone.utc) - timedelta(hours=6)
    mailbox = "restarted@probeps.com"

    fake_repo = _FakeMailboxPollStateRepository(checkpoints={mailbox: persisted_checkpoint})
    monkeypatch.setattr(graph_mail_poller_module, "MailboxPollStateRepository", fake_repo)
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
    )

    async def _fake_resolve_mailboxes(settings):
        return [mailbox]

    monkeypatch.setattr(
        graph_mail_poller_module, "_resolve_mailboxes_to_poll", _fake_resolve_mailboxes
    )

    seen_since = {}

    class _CapturingClient(_FakeGraphMailProviderClient):
        async def list_new_messages(self, since):
            seen_since["value"] = since
            return await super().list_new_messages(since)

    # __name__ isn't inherited for this defensive check's purposes —
    # _poll_one_mailbox compares __class__.__name__ literally, same
    # reason _FakeGraphMailProviderClient itself needs the same patch
    # above.
    _CapturingClient.__name__ = "GraphMailProviderClient"

    monkeypatch.setattr(
        graph_mail_poller_module,
        "get_mail_provider_client",
        lambda settings, mailbox_address=None: _CapturingClient(messages=[]),
    )

    await graph_mail_poller_module.poll_new_messages(settings)

    # Used the persisted checkpoint as `since`, not
    # now - INITIAL_LOOKBACK_MINUTES.
    assert seen_since["value"] == persisted_checkpoint
    # And the successful tick persisted its own new checkpoint back.
    assert len(fake_repo.record_success_calls) == 1
    assert fake_repo.record_success_calls[0][0] == mailbox


async def test_poll_new_messages_only_seeds_once_per_process(monkeypatch):
    """Fix 2: the persisted-checkpoint seed only ever runs once per
    process (checkpoints_seeded), not once per tick — a second tick
    must not re-read/override an in-memory checkpoint that's already
    been advanced past the persisted value."""

    settings = _settings()
    mailbox = "seeded-once@probeps.com"
    stale_persisted = datetime.now(timezone.utc) - timedelta(hours=6)

    fake_repo = _FakeMailboxPollStateRepository(checkpoints={mailbox: stale_persisted})
    monkeypatch.setattr(graph_mail_poller_module, "MailboxPollStateRepository", fake_repo)
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
    )

    async def _fake_resolve_mailboxes(settings):
        return [mailbox]

    monkeypatch.setattr(
        graph_mail_poller_module, "_resolve_mailboxes_to_poll", _fake_resolve_mailboxes
    )
    monkeypatch.setattr(
        graph_mail_poller_module,
        "get_mail_provider_client",
        lambda settings, mailbox_address=None: _FakeGraphMailProviderClient(messages=[]),
    )

    await graph_mail_poller_module.poll_new_messages(settings)
    advanced_checkpoint = graph_mail_poller_module._state.checkpoints[mailbox]
    assert advanced_checkpoint > stale_persisted

    # A second tick must not re-seed from the (now stale) persisted
    # value — get_all_checkpoints should not be called again.
    fake_repo.checkpoints[mailbox] = stale_persisted  # simulate a stale read if it were re-seeded
    await graph_mail_poller_module.poll_new_messages(settings)
    assert graph_mail_poller_module._state.checkpoints[mailbox] >= advanced_checkpoint


async def test_mailbox_stall_triggers_alert_after_threshold(monkeypatch):
    """Fix 3: a mailbox that's been failing to fetch since before
    Settings.graph_mail_poll_stall_alert_minutes must trigger exactly
    one notify_mailbox_poll_stalled call, and mark_alerted so a later
    tick doesn't repeat it every time."""

    settings = _settings(graph_mail_poll_stall_alert_minutes=15)
    mailbox = "stalled@probeps.com"
    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    fake_repo = _FakeMailboxPollStateRepository(
        states={
            mailbox: _FakeMailboxPollState(
                consecutive_failures=3, last_success_at=long_ago, last_alerted_at=None
            )
        }
    )
    monkeypatch.setattr(graph_mail_poller_module, "MailboxPollStateRepository", fake_repo)
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
    )

    alert_calls = []

    async def _fake_notify(db, *, mailbox_address, consecutive_failures, error_summary):
        alert_calls.append((mailbox_address, consecutive_failures))

    monkeypatch.setattr(graph_mail_poller_module, "notify_mailbox_poll_stalled", _fake_notify)

    await graph_mail_poller_module._record_mailbox_fetch_failure_and_maybe_alert(
        settings, mailbox, error_summary="GraphAPIError(403): forbidden"
    )

    assert alert_calls == [(mailbox, 4)]
    assert fake_repo.mark_alerted_calls == [mailbox]


async def test_mailbox_stall_does_not_alert_before_threshold(monkeypatch):
    """A mailbox that only just started failing (well within the
    stall-alert window) must not alert yet."""

    settings = _settings(graph_mail_poll_stall_alert_minutes=15)
    mailbox = "just-started-failing@probeps.com"
    recently = datetime.now(timezone.utc) - timedelta(minutes=2)

    fake_repo = _FakeMailboxPollStateRepository(
        states={
            mailbox: _FakeMailboxPollState(
                consecutive_failures=1, last_success_at=recently, last_alerted_at=None
            )
        }
    )
    monkeypatch.setattr(graph_mail_poller_module, "MailboxPollStateRepository", fake_repo)
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
    )

    alert_calls = []

    async def _fake_notify(db, *, mailbox_address, consecutive_failures, error_summary):
        alert_calls.append(mailbox_address)

    monkeypatch.setattr(graph_mail_poller_module, "notify_mailbox_poll_stalled", _fake_notify)

    await graph_mail_poller_module._record_mailbox_fetch_failure_and_maybe_alert(
        settings, mailbox, error_summary="GraphAPIError(403): forbidden"
    )

    assert alert_calls == []
    assert fake_repo.mark_alerted_calls == []


async def test_mailbox_stall_does_not_realert_immediately(monkeypatch):
    """A mailbox already alerted on within this same stall window must
    not be re-alerted on every subsequent tick."""

    settings = _settings(graph_mail_poll_stall_alert_minutes=15)
    mailbox = "already-alerted@probeps.com"
    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    recently_alerted = datetime.now(timezone.utc) - timedelta(minutes=1)

    fake_repo = _FakeMailboxPollStateRepository(
        states={
            mailbox: _FakeMailboxPollState(
                consecutive_failures=5,
                last_success_at=long_ago,
                last_alerted_at=recently_alerted,
            )
        }
    )
    monkeypatch.setattr(graph_mail_poller_module, "MailboxPollStateRepository", fake_repo)
    monkeypatch.setattr(
        graph_mail_poller_module, "AsyncSessionLocal", lambda: _CommittableFakeDBSession()
    )

    alert_calls = []

    async def _fake_notify(db, *, mailbox_address, consecutive_failures, error_summary):
        alert_calls.append(mailbox_address)

    monkeypatch.setattr(graph_mail_poller_module, "notify_mailbox_poll_stalled", _fake_notify)

    await graph_mail_poller_module._record_mailbox_fetch_failure_and_maybe_alert(
        settings, mailbox, error_summary="GraphAPIError(403): forbidden"
    )

    assert alert_calls == []

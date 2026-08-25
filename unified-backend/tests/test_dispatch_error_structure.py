# test_dispatch_error_structure.py
#
# Phase 2 hardening: structured dispatch-error observability. Verifies
# GraphAPIError's new `operation` field survives through
# OutboundDispatcher.dispatch()'s OutboundDispatchError wrapping, that
# a failure mid-_send_via_draft (after a real Graph draft was already
# created) is annotated with `orphaned_draft_id`, and that
# InteractionService._dispatch_and_record stores both a tagged
# dispatch_error string and a payload-only orphaned_provider_draft_id
# key (never promoted to provider_message_id) — no DB, no real network
# call.

from uuid import uuid4

import pytest

from app.ticketing.schemas.payloads import EnvelopeAttachment, OutboundEnvelope
from app.ticketing.services.graph_client import GraphAPIError, GraphMailProviderClient
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.outbound_dispatcher import OutboundDispatchError, OutboundDispatcher


def _envelope(**overrides) -> OutboundEnvelope:
    base = dict(
        from_email="clientinbox@example.com",
        to_email="patient@example.com",
        subject="Re: Test",
        message_id="<new-id@example.com>",
        body="Hello there.",
    )
    base.update(overrides)
    return OutboundEnvelope(**base)


# ---------------------------------------------------------
# OutboundDispatcher: GraphAPIError's operation/status_code/
# orphaned_draft_id pass through into OutboundDispatchError
# ---------------------------------------------------------


class _StubFailingClientWithOperation:
    async def send_email(self, envelope):
        exc = GraphAPIError(502, "bad gateway", operation="sendMail")
        raise exc


async def test_dispatch_error_carries_operation_and_status_code(monkeypatch):
    monkeypatch.setattr(
        "app.ticketing.services.outbound_dispatcher.get_mail_provider_client",
        lambda mailbox_address=None, storage_service=None: _StubFailingClientWithOperation(),
    )

    dispatcher = OutboundDispatcher()

    with pytest.raises(OutboundDispatchError) as exc_info:
        await dispatcher.dispatch(uuid4(), _envelope())

    assert exc_info.value.operation == "sendMail"
    assert exc_info.value.status_code == 502
    assert exc_info.value.orphaned_provider_draft_id is None


class _StubFailingClientNoExtras:
    async def send_email(self, envelope):
        raise RuntimeError("plain failure, no operation/status_code attributes")


async def test_dispatch_error_defaults_to_none_for_a_plain_exception(monkeypatch):
    """A non-GraphAPIError failure (e.g. a bare RuntimeError) must not
    crash the getattr-based extraction — it just yields None fields."""

    monkeypatch.setattr(
        "app.ticketing.services.outbound_dispatcher.get_mail_provider_client",
        lambda mailbox_address=None, storage_service=None: _StubFailingClientNoExtras(),
    )

    dispatcher = OutboundDispatcher()

    with pytest.raises(OutboundDispatchError) as exc_info:
        await dispatcher.dispatch(uuid4(), _envelope())

    assert exc_info.value.operation is None
    assert exc_info.value.status_code is None
    assert exc_info.value.orphaned_provider_draft_id is None


# ---------------------------------------------------------
# GraphMailProviderClient._send_via_draft: orphaned_draft_id is set
# only for a failure AFTER draft creation, never before
# ---------------------------------------------------------


def _draft_client(monkeypatch) -> GraphMailProviderClient:
    client = GraphMailProviderClient(
        auth_client=None,
        mailbox_address="mailbox@example.com",
        api_base_url="https://graph.microsoft.com/v1.0",
    )
    return client


def _large_attachment() -> EnvelopeAttachment:
    return EnvelopeAttachment(
        filename="big.pdf",
        content_type="application/pdf",
        storage_key="some/key.pdf",
        size_bytes=10 * 1024 * 1024,
    )


async def test_send_via_draft_annotates_orphaned_draft_id_after_creation(monkeypatch):
    client = _draft_client(monkeypatch)

    async def _fake_create_new_draft(envelope):
        return "draft-abc-123"

    async def _fake_add_large_attachment(draft_id, attachment):
        raise GraphAPIError(500, "upload session failed", operation="createUploadSession")

    monkeypatch.setattr(client, "_create_new_draft", _fake_create_new_draft)
    monkeypatch.setattr(client, "_add_large_attachment", _fake_add_large_attachment)

    with pytest.raises(GraphAPIError) as exc_info:
        await client._send_via_draft(_envelope(), [], [_large_attachment()])

    assert exc_info.value.orphaned_draft_id == "draft-abc-123"
    assert exc_info.value.operation == "createUploadSession"


async def test_send_via_draft_no_orphan_when_draft_creation_itself_fails(monkeypatch):
    """A failure creating the draft itself means no real Graph draft
    exists at all — orphaned_draft_id must stay unset."""

    client = _draft_client(monkeypatch)

    async def _fake_create_new_draft_fails(envelope):
        raise GraphAPIError(500, "create draft failed", operation="createDraft")

    monkeypatch.setattr(client, "_create_new_draft", _fake_create_new_draft_fails)

    with pytest.raises(GraphAPIError) as exc_info:
        await client._send_via_draft(_envelope(), [], [_large_attachment()])

    assert exc_info.value.orphaned_draft_id is None
    assert exc_info.value.operation == "createDraft"


# ---------------------------------------------------------
# InteractionService._dispatch_and_record: tagged dispatch_error +
# payload-only orphaned_provider_draft_id
# ---------------------------------------------------------


class _FakeInteraction:
    def __init__(self):
        self.interaction_id = uuid4()
        self.payload = {"dispatch_status": "PENDING_SEND"}


class _FailingDispatcher:
    def __init__(self, exc):
        self._exc = exc

    async def dispatch(self, interaction_id, envelope):
        raise self._exc


class _RecordingInteractionRepository:
    def __init__(self):
        self.updates = []

    async def update(self, interaction, request):
        self.updates.append(request)
        return interaction

    @property
    def db(self):
        return self

    async def commit(self):
        pass


async def test_dispatch_and_record_tags_error_and_stores_orphaned_draft(monkeypatch):
    exc = OutboundDispatchError(
        "Graph API error 500: upload session failed",
        operation="createUploadSession",
        status_code=500,
        orphaned_provider_draft_id="draft-xyz",
    )

    interaction_repository = _RecordingInteractionRepository()
    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=None,
        user_repository=None,
        outbound_dispatcher=_FailingDispatcher(exc),
    )

    interaction = _FakeInteraction()

    with pytest.raises(Exception):
        await service._dispatch_and_record(interaction, _envelope())

    assert len(interaction_repository.updates) == 1
    update_request = interaction_repository.updates[0]
    assert update_request.payload["dispatch_status"] == "FAILED"
    assert update_request.payload["dispatch_error"].startswith("[graph:createUploadSession:500] ")
    assert update_request.payload["orphaned_provider_draft_id"] == "draft-xyz"
    # Never conflated with provider_message_id's own documented meaning.
    assert update_request.provider_message_id is None


async def test_dispatch_and_record_no_orphan_key_when_none_reported(monkeypatch):
    exc = OutboundDispatchError("Graph API error 500: boom", operation="sendMail", status_code=500)

    interaction_repository = _RecordingInteractionRepository()
    service = InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=None,
        user_repository=None,
        outbound_dispatcher=_FailingDispatcher(exc),
    )

    interaction = _FakeInteraction()

    with pytest.raises(Exception):
        await service._dispatch_and_record(interaction, _envelope())

    update_request = interaction_repository.updates[0]
    assert "orphaned_provider_draft_id" not in update_request.payload
    assert update_request.payload["dispatch_error"].startswith("[graph:sendMail:500] ")

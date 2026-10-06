# test_read_receipt_request_plumbing.py
#
# The "Request read receipt" flag must travel the whole outbound chain
# and must never silently disappear on one path:
#
#   request -> InteractionService -> build_*_envelope -> OutboundEnvelope
#   -> (persisted) -> dispatch / retry / undo-send -> provider
#
# and through every DRAFT (save -> reopen -> send), whose send endpoints
# take no per-send options. With the read_receipts_enabled setting OFF
# (the default) the flag is ignored everywhere, so every send is exactly
# as before the feature existed. Service-level, mocked repositories —
# the same style as test_send_idempotency.py / test_compose_draft.py.

import ast
import inspect
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.interaction import Interaction
from app.ticketing.schemas.compose import (
    ComposeDraftSaveRequest,
    ComposeEmailRequest,
    ComposeEmailResponse,
)
from app.ticketing.schemas.interaction import DraftSaveRequest
from app.ticketing.schemas.payloads import EmailPayload
from app.ticketing.schemas.ticket_action import (
    InteractionReplyRequest,
    InteractionReplyResponse,
    ReplyCreate,
)
from app.ticketing.schemas.ticket_draft import TicketReplyDraftSaveRequest
from app.ticketing.services import interaction_service as interaction_service_module
from app.ticketing.services.email_envelope import (
    build_compose_envelope,
    build_reply_envelope,
)
from app.ticketing.services.interaction_service import (
    InteractionService,
    _effective_read_receipt_requested,
)
from tests.test_send_idempotency import (
    _build_service,
    _global_inbox_user,
    _root_interaction,
)


def _settings(**overrides) -> Settings:
    base = dict(
        database_url="postgresql+asyncpg://user:pass@localhost/test",
        jwt_secret_key="test-secret",
        sla_sweep_shared_secret="test-sweep-secret",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _stub_setting(monkeypatch, enabled: bool):
    async def _fake(db):
        return enabled

    monkeypatch.setattr(interaction_service_module, "is_read_receipts_enabled", _fake)


@pytest.fixture
def flag_on(monkeypatch):
    _stub_setting(monkeypatch, True)


@pytest.fixture
def flag_off(monkeypatch):
    _stub_setting(monkeypatch, False)


# ---------------------------------------------------------------
# The feature flag
# ---------------------------------------------------------------


def test_there_is_no_environment_flag_the_database_setting_is_the_only_source():
    # Single source of truth: the Settings UI / `app_settings` table. A
    # second env-var switch would be a confusing duplicate.
    assert "read_receipts_enabled" not in Settings.model_fields


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("requested", [True, False])
async def test_effective_flag_requires_both_the_request_and_the_setting(
    monkeypatch, enabled, requested
):
    _stub_setting(monkeypatch, enabled)
    assert await _effective_read_receipt_requested(object(), requested) is (enabled and requested)


async def test_the_setting_is_not_even_read_when_no_receipt_was_requested(monkeypatch):
    async def _must_not_run(db):
        raise AssertionError("an ordinary send must not touch the settings table")

    monkeypatch.setattr(interaction_service_module, "is_read_receipts_enabled", _must_not_run)
    assert await _effective_read_receipt_requested(object(), False) is False


# ---------------------------------------------------------------
# Envelope builders
# ---------------------------------------------------------------


def _inbound() -> EmailPayload:
    return EmailPayload(
        subject="Question", body="hi", from_email="patient@example.com",
        to_email="ticketing@example.com",
    )


def test_reply_envelope_passes_the_flag_through_and_defaults_off():
    base = dict(
        from_email="ticketing@example.com", inbound_payload=_inbound(),
        inbound_message_id="<in@example.com>", body="Reply",
    )
    assert build_reply_envelope(**base).read_receipt_requested is False
    assert build_reply_envelope(**base, read_receipt_requested=True).read_receipt_requested is True


def test_compose_envelope_passes_the_flag_through_and_defaults_off():
    base = dict(
        from_email="ticketing@example.com", to_email="a@example.com",
        subject="s", body="b",
    )
    assert build_compose_envelope(**base).read_receipt_requested is False
    assert build_compose_envelope(**base, read_receipt_requested=True).read_receipt_requested is True


def test_envelope_model_dump_carries_the_flag_for_retry_replay():
    envelope = build_compose_envelope(
        from_email="ticketing@example.com", to_email="a@example.com",
        subject="s", body="b", read_receipt_requested=True,
    )
    assert envelope.model_dump()["read_receipt_requested"] is True


# ---------------------------------------------------------------
# Static guard: no builder call in InteractionService may forget it
# ---------------------------------------------------------------


def test_every_user_send_path_passes_the_flag_to_its_envelope_builder():
    tree = ast.parse(inspect.getsource(interaction_service_module))
    calls: list[tuple[str, str, bool]] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self):
            self.function = None

        def visit_AsyncFunctionDef(self, node):
            previous, self.function = self.function, node.name
            self.generic_visit(node)
            self.function = previous

        def visit_Call(self, node):
            name = getattr(node.func, "id", None)
            if name in ("build_reply_envelope", "build_compose_envelope"):
                keywords = {kw.arg for kw in node.keywords}
                calls.append((self.function, name, "read_receipt_requested" in keywords))
            self.generic_visit(node)

    _Visitor().visit(tree)

    by_function = {(function, name): passes for function, name, passes in calls}
    # Reply (ticket), reply (pre-ticket) and compose all forward it...
    assert by_function[("add_reply", "build_reply_envelope")] is True
    assert by_function[("add_interaction_reply", "build_reply_envelope")] is True
    assert by_function[("compose_email", "build_compose_envelope")] is True
    # ...and Forward is deliberately OUT OF SCOPE (never requests one).
    assert by_function[("forward_to_internal_user", "build_compose_envelope")] is False
    # Nothing else builds an envelope without being accounted for here.
    assert len(calls) == 4


# ---------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------


def test_every_request_and_draft_schema_defaults_the_flag_off():
    assert ReplyCreate(message="m").read_receipt_requested is False
    assert InteractionReplyRequest(message="m").read_receipt_requested is False
    assert ComposeEmailRequest(
        client_id=uuid.uuid4(), to_email="a@example.com", subject="s", message="m"
    ).read_receipt_requested is False
    assert DraftSaveRequest(message="m").read_receipt_requested is False
    assert TicketReplyDraftSaveRequest().read_receipt_requested is False
    assert ComposeDraftSaveRequest().read_receipt_requested is False


# ---------------------------------------------------------------
# Drafts: the flag is saved with the draft, restored on reopen, and
# applied at draft-send time
# ---------------------------------------------------------------


def test_unticked_draft_payloads_are_byte_identical_to_before_the_feature():
    compose = InteractionService._compose_draft_payload(ComposeDraftSaveRequest(subject="s"))
    ticket = InteractionService._ticket_reply_draft_payload(TicketReplyDraftSaveRequest())
    assert "read_receipt_requested" not in compose
    assert "read_receipt_requested" not in ticket


def test_ticked_draft_payloads_store_the_flag():
    compose = InteractionService._compose_draft_payload(
        ComposeDraftSaveRequest(read_receipt_requested=True)
    )
    ticket = InteractionService._ticket_reply_draft_payload(
        TicketReplyDraftSaveRequest(read_receipt_requested=True)
    )
    assert compose["read_receipt_requested"] is True
    assert ticket["read_receipt_requested"] is True


def _draft_row(payload, *, itype="EMAIL", ticket_id=None) -> Interaction:
    return Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type=itype,
        status=InteractionStatus.PENDING,
        direction=InteractionDirection.OUTBOUND,
        payload=payload,
        ticket_id=ticket_id,
        is_draft=True,
        is_visible=True,
        created_at=datetime.now(timezone.utc),
    )


def test_draft_responses_restore_the_checkbox_on_reopen():
    compose = InteractionService._compose_draft_to_response(
        _draft_row({"read_receipt_requested": True}), []
    )
    assert compose.read_receipt_requested is True
    assert InteractionService._compose_draft_to_response(_draft_row({}), []).read_receipt_requested is False

    ticket = InteractionService._ticket_reply_draft_to_response(
        _draft_row({"read_receipt_requested": True}, itype="REPLY", ticket_id=uuid.uuid4())
    )
    assert ticket.read_receipt_requested is True


async def test_pre_ticket_draft_save_persists_and_clears_the_flag():
    service = _build_service(AsyncMock())
    draft = _draft_row({"message": "m", "cc": [], "bcc": []}, itype="REPLY")

    await service._persist_draft_receipt_flag(draft, True)
    assert draft.payload["read_receipt_requested"] is True
    assert draft.payload["message"] == "m"  # nothing else touched

    await service._persist_draft_receipt_flag(draft, False)
    assert "read_receipt_requested" not in draft.payload  # byte-identical again


async def test_pre_ticket_draft_send_applies_the_saved_flag():
    root = _root_interaction()
    draft = _draft_row(
        {"message": "draft body", "cc": [], "bcc": [], "read_receipt_requested": True},
        itype="REPLY",
    )
    repo = AsyncMock()
    repo.get_by_id.return_value = root
    repo.find_thread_root.return_value = root
    repo.get_by_idempotency_key.return_value = None
    repo.get_draft.return_value = draft
    service = _build_service(repo)
    service.attachment_repository = AsyncMock()
    captured: list[InteractionReplyRequest] = []

    async def _fake_add_interaction_reply(
        interaction_id, request, current_user, existing_attachment_source_interaction_id=None
    ):
        captured.append(request)
        return InteractionReplyResponse(
            interaction_id=uuid.uuid4(), parent_interaction_id=root.interaction_id,
            message=request.message, created_at=datetime.now(timezone.utc),
        )

    service.add_interaction_reply = _fake_add_interaction_reply

    await service.send_draft(interaction_id=root.interaction_id, current_user=_global_inbox_user())

    assert captured[0].read_receipt_requested is True


async def test_pre_ticket_draft_send_without_the_flag_stays_off():
    root = _root_interaction()
    draft = _draft_row({"message": "draft body", "cc": [], "bcc": []}, itype="REPLY")
    repo = AsyncMock()
    repo.get_by_id.return_value = root
    repo.find_thread_root.return_value = root
    repo.get_by_idempotency_key.return_value = None
    repo.get_draft.return_value = draft
    service = _build_service(repo)
    service.attachment_repository = AsyncMock()
    captured = []

    async def _fake(interaction_id, request, current_user, existing_attachment_source_interaction_id=None):
        captured.append(request)
        return InteractionReplyResponse(
            interaction_id=uuid.uuid4(), parent_interaction_id=root.interaction_id,
            message="m", created_at=datetime.now(timezone.utc),
        )

    service.add_interaction_reply = _fake
    await service.send_draft(interaction_id=root.interaction_id, current_user=_global_inbox_user())

    assert captured[0].read_receipt_requested is False


async def test_ticket_reply_draft_send_applies_the_saved_flag():
    ticket_id = uuid.uuid4()
    draft = _draft_row(
        {"message": "m", "to_email": "a@example.com", "cc": [], "bcc": [],
         "read_receipt_requested": True},
        itype="REPLY", ticket_id=ticket_id,
    )
    repo = AsyncMock()
    repo.get_ticket_draft.return_value = draft
    service = _build_service(repo)
    captured: list[ReplyCreate] = []

    async def _fake_add_reply(ticket_id_arg, request, current_user):
        captured.append(request)
        return SimpleNamespace(interaction_id=uuid.uuid4())

    service.add_reply = _fake_add_reply

    await service.send_ticket_reply_draft(ticket_id, _global_inbox_user())

    assert captured[0].read_receipt_requested is True
    repo.delete_draft.assert_awaited_once()


async def test_compose_draft_send_applies_the_saved_flag(monkeypatch):
    async def _pass(*a, **k):
        return None

    monkeypatch.setattr(
        "app.ticketing.services.interaction_service.ensure_recipients_are_valid", _pass
    )
    user = SimpleNamespace(
        user_id=uuid.uuid4(), name="Agent", role=SimpleNamespace(name="Staff"),
        permissions=[], designation=None, department=None, phone_number=None,
    )
    draft = _draft_row({
        "client_id": str(uuid.uuid4()), "category_id": None,
        "to_email": "client@example.com", "to_emails": [], "cc": [], "bcc": [],
        "subject": "s", "message": "m", "read_receipt_requested": True,
    })
    draft.performed_by = user.user_id
    repo = AsyncMock()
    repo.get_by_id.return_value = draft
    service = _build_service(repo)
    service.attachment_repository = AsyncMock()
    captured = []

    async def _fake_compose_email(request, current_user, files=None,
                                  inline_image_interaction_ids=None,
                                  existing_attachment_source_interaction_id=None):
        captured.append(request)
        return ComposeEmailResponse(
            interaction_id=uuid.uuid4(), created_at=datetime.now(timezone.utc)
        )

    service.compose_email = _fake_compose_email

    await service.send_compose_draft(draft.interaction_id, user)

    assert captured[0].read_receipt_requested is True


# ---------------------------------------------------------------
# End to end through the real compose_email: flag on vs off
# ---------------------------------------------------------------


async def _compose(flag_requested: bool):
    repo = AsyncMock()
    repo.get_by_idempotency_key.return_value = None
    repo.create.side_effect = lambda create: SimpleNamespace(
        interaction_id=uuid.uuid4(), created_at=datetime.now(timezone.utc),
        payload=create.payload, subject=create.subject, status=create.status,
        direction=create.direction, client_id=create.client_id, ticket_id=None,
    )
    service = _build_service(repo)
    client = AsyncMock()
    client.client_id = uuid.uuid4()
    client.is_active = True
    client.inbox_email = "shared@example.com"
    client.account_manager_id = uuid.uuid4()
    client.name = "Client"
    service.client_repository.get_by_id.return_value = client
    service.user_repository.get_by_id.return_value = None
    scheduled: list = []

    async def _capture(interaction, envelope):
        scheduled.append(envelope)

    service._schedule_delayed_send = _capture
    user = SimpleNamespace(
        user_id=uuid.uuid4(), name="Agent", role=SimpleNamespace(name="Staff"),
        permissions=["communication:create"], designation=None, department=None,
        phone_number=None,
    )
    await service.compose_email(
        request=ComposeEmailRequest(
            client_id=client.client_id, to_email="someone@painmedpa.com",
            subject="Test", message="Hello", read_receipt_requested=flag_requested,
        ),
        current_user=user,
    )
    return scheduled[0]


async def test_compose_with_flag_on_puts_the_request_on_the_envelope(flag_on, monkeypatch):
    monkeypatch.setattr(interaction_service_module, "ensure_recipients_are_valid", AsyncMock())
    envelope = await _compose(True)
    assert envelope.read_receipt_requested is True


async def test_compose_with_setting_off_ignores_a_client_supplied_flag(flag_off, monkeypatch):
    monkeypatch.setattr(interaction_service_module, "ensure_recipients_are_valid", AsyncMock())
    envelope = await _compose(True)
    assert envelope.read_receipt_requested is False


async def test_compose_without_the_flag_is_unchanged(flag_on, monkeypatch):
    monkeypatch.setattr(interaction_service_module, "ensure_recipients_are_valid", AsyncMock())
    envelope = await _compose(False)
    assert envelope.read_receipt_requested is False


# ---------------------------------------------------------------
# GET /inbox/features — how the composer learns the setting
# ---------------------------------------------------------------


@pytest.mark.parametrize("enabled", [True, False])
async def test_features_endpoint_mirrors_the_database_setting(monkeypatch, enabled):
    from app.ticketing.api import inbox as inbox_api

    async def _fake(db):
        return enabled

    monkeypatch.setattr(inbox_api, "is_read_receipts_enabled", _fake)

    response = await inbox_api.get_mail_features(
        current_user=_global_inbox_user(), db=object()
    )

    assert response.read_receipts_enabled is enabled


def test_features_route_is_registered_before_any_dynamic_inbox_route():
    from app.ticketing.api.inbox import router

    paths = [r.path for r in router.routes]
    features = paths.index("/inbox/features")
    dynamic = [
        i for i, r in enumerate(router.routes)
        if r.path == "/inbox/{interaction_id}" and "GET" in r.methods
    ]
    assert dynamic and features < dynamic[0]


# ---------------------------------------------------------------
# API response shapes
# ---------------------------------------------------------------


def _outbound_row(**payload) -> Interaction:
    return Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="REPLY",
        status=InteractionStatus.ASSIGNED,
        direction=InteractionDirection.OUTBOUND,
        payload=payload or {"message": "m"},
        is_visible=True,
        created_at=datetime.now(timezone.utc),
    )


def test_thread_responses_carry_the_per_recipient_list_in_the_documented_shape():
    from app.ticketing.schemas.interaction import ReadReceiptStatusResponse
    from app.ticketing.services.interaction_service import _to_response
    from app.ticketing.services.open_email_service import _reply_to_response

    statuses = [
        ReadReceiptStatusResponse(
            recipient_email="a@example.com",
            status="CONFIRMED",
            read_at=datetime(2026, 10, 6, 8, 21, 37, tzinfo=timezone.utc),
        ),
        ReadReceiptStatusResponse(recipient_email="b@example.com", status="REQUESTED"),
    ]
    row = _outbound_row()

    for response in (
        _to_response(row, read_receipts=statuses),
        _reply_to_response(row, [], statuses),
    ):
        dumped = [r.model_dump() for r in response.read_receipts]
        assert dumped == [
            {
                "recipient_email": "a@example.com",
                "status": "CONFIRMED",
                "read_at": datetime(2026, 10, 6, 8, 21, 37, tzinfo=timezone.utc),
            },
            {"recipient_email": "b@example.com", "status": "REQUESTED", "read_at": None},
        ]
        # Nothing about the MDN itself leaks into the API.
        assert set(dumped[0]) == {"recipient_email", "status", "read_at"}


def test_responses_default_to_no_receipts():
    from app.ticketing.services.interaction_service import _to_response
    from app.ticketing.services.open_email_service import _reply_to_response

    row = _outbound_row()
    assert _to_response(row).read_receipts == []
    assert _reply_to_response(row, []).read_receipts == []


def test_open_email_response_exposes_the_draft_flag_and_root_receipts_by_default_off():
    from app.ticketing.schemas.open_email import OpenEmailResponse

    fields = OpenEmailResponse.model_fields
    assert fields["draft_read_receipt_requested"].default is False
    assert fields["read_receipts"].default_factory() == []


# ---------------------------------------------------------------
# Integration: Settings -> compose service -> envelope -> Graph request
# ---------------------------------------------------------------


async def _compose_then_send_to_graph(monkeypatch, *, setting_on: bool, requested: bool):
    from tests.test_graph_read_receipt_send import _provider

    _stub_setting(monkeypatch, setting_on)
    monkeypatch.setattr(interaction_service_module, "ensure_recipients_are_valid", AsyncMock())
    envelope = await _compose(requested)
    client, fake = _provider(monkeypatch)
    result = await client.send_email(envelope)
    return fake, result


async def test_setting_off_then_a_normal_email_requests_no_receipt(monkeypatch):
    fake, result = await _compose_then_send_to_graph(monkeypatch, setting_on=False, requested=False)

    assert "isReadReceiptRequested" not in fake.posts("/messages")[0]["json"]
    assert result.status == "SENT"  # existing email sending still works


async def test_setting_off_ignores_even_a_forced_request(monkeypatch):
    fake, result = await _compose_then_send_to_graph(monkeypatch, setting_on=False, requested=True)

    assert "isReadReceiptRequested" not in fake.posts("/messages")[0]["json"]
    assert result.status == "SENT"


async def test_setting_on_and_requested_graph_receives_the_flag(monkeypatch):
    fake, result = await _compose_then_send_to_graph(monkeypatch, setting_on=True, requested=True)

    assert fake.posts("/messages")[0]["json"]["isReadReceiptRequested"] is True
    assert result.internet_message_id  # the real id is captured for matching


async def test_setting_on_but_not_requested_still_sends_a_normal_email(monkeypatch):
    fake, _ = await _compose_then_send_to_graph(monkeypatch, setting_on=True, requested=False)

    assert "isReadReceiptRequested" not in fake.posts("/messages")[0]["json"]

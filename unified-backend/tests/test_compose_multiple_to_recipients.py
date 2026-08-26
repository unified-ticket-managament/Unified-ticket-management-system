# test_compose_multiple_to_recipients.py
#
# Regression coverage for the newly-reported Compose bug: entering
# multiple recipients in Compose's "To" field used to result in only
# the first becoming a real "To" recipient, with every other one
# silently downgraded into Cc — both in the outbound Graph envelope
# and in the persisted Sent record — because ComposeEmailRequest only
# ever had a single `to_email: EmailStr | None` field. `to_emails`
# (plural) is the fix: it's additively merged with `to_email` into one
# effective "To" list before Distribution runs on top, exactly
# mirroring how Forward's own multi-recipient envelope already works.
#
# Service-level, mocked repository/client — same style as
# test_send_idempotency.py's own compose_email coverage, since this is
# about the recipient-list construction, not dispatch itself (already
# covered by test_finalize_envelope_attachments.py /
# test_outbound_dispatcher.py).

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.ticketing.models.interaction import Interaction
from app.ticketing.schemas.compose import ComposeEmailRequest
from app.ticketing.services.interaction_service import InteractionService


def _current_user() -> SimpleNamespace:
    return SimpleNamespace(
        user_id=uuid.uuid4(),
        name="Agent",
        role=SimpleNamespace(name="Staff"),
        permissions=["communication:reply_external"],
        designation=None,
        department=None,
        phone_number=None,
    )


def _fake_client():
    client = AsyncMock()
    client.client_id = uuid.uuid4()
    client.is_active = True
    client.inbox_email = "shared@example.com"
    client.account_manager_id = uuid.uuid4()
    client.name = "Test Client"
    return client


async def _compose(monkeypatch, *, to_email=None, to_emails=None, cc=None, distribution_list_ids=None):
    async def _pass(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.ticketing.services.interaction_service.ensure_recipients_are_valid", _pass
    )

    repo = AsyncMock()
    repo.get_by_idempotency_key.return_value = None

    def _echo_create(data):
        return Interaction(
            interaction_id=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            **data.model_dump(),
        )

    repo.create.side_effect = _echo_create

    service = InteractionService(
        interaction_repository=repo,
        ticket_repository=AsyncMock(),
        user_repository=AsyncMock(),
        client_repository=AsyncMock(),
        distribution_list_repository=AsyncMock(),
    )

    fake_client = _fake_client()
    service.client_repository.get_by_id.return_value = fake_client
    service.user_repository.get_by_id.return_value = None

    async def _no_dl_members(*args, **kwargs):
        return []

    from app.ticketing.services import interaction_service as module

    monkeypatch.setattr(module, "resolve_distribution_list_emails", _no_dl_members)

    request = ComposeEmailRequest(
        client_id=fake_client.client_id,
        to_email=to_email,
        to_emails=to_emails or [],
        cc=cc or [],
        distribution_list_ids=distribution_list_ids or [],
        subject="Test",
        message="Hello",
    )

    response = await service.compose_email(request=request, current_user=_current_user())

    created_call = repo.create.call_args.args[0]
    return response, created_call


async def test_single_to_recipient_unchanged(monkeypatch):
    _, created = await _compose(monkeypatch, to_email="a@example.com")

    assert created.payload["to_emails"] == ["a@example.com"]
    assert created.payload["cc"] == []


async def test_two_to_recipients_both_land_in_to_not_cc(monkeypatch):
    _, created = await _compose(
        monkeypatch, to_email="a@example.com", to_emails=["b@example.com"]
    )

    assert created.payload["to_emails"] == ["a@example.com", "b@example.com"]
    assert created.payload["cc"] == []


async def test_three_or_more_to_recipients_all_land_in_to(monkeypatch):
    _, created = await _compose(
        monkeypatch,
        to_email="a@example.com",
        to_emails=["b@example.com", "c@example.com", "d@example.com"],
    )

    assert created.payload["to_emails"] == [
        "a@example.com",
        "b@example.com",
        "c@example.com",
        "d@example.com",
    ]
    assert created.payload["cc"] == []


async def test_to_plus_explicit_cc_both_remain_separate(monkeypatch):
    _, created = await _compose(
        monkeypatch,
        to_email="a@example.com",
        to_emails=["b@example.com"],
        cc=["cc-person@example.com"],
    )

    assert created.payload["to_emails"] == ["a@example.com", "b@example.com"]
    assert created.payload["cc"] == ["cc-person@example.com"]


async def test_no_duplicate_recipient_when_typed_address_also_in_to_emails(monkeypatch):
    _, created = await _compose(
        monkeypatch, to_email="a@example.com", to_emails=["A@Example.com", "b@example.com"]
    )

    # dedupe_emails_case_insensitive collapses the case-insensitive
    # duplicate — the same behavior every other multi-recipient path
    # (Forward, Distribution Lists) already relies on.
    assert created.payload["to_emails"] == ["a@example.com", "b@example.com"]


async def test_reply_forward_payload_construction_is_untouched(monkeypatch):
    """
    Guard against a regression to the unrelated single-recipient shape
    — Reply/Reply All/Forward never pass through compose_email at all
    (see add_reply/add_interaction_reply/forward_to_internal_user),
    so this only re-confirms compose_email itself still accepts a
    plain single to_email with no to_emails, unchanged from before.
    """

    _, created = await _compose(monkeypatch, to_email="solo@example.com", to_emails=[])

    assert created.payload["to_emails"] == ["solo@example.com"]


def test_compose_email_request_requires_at_least_one_recipient_source():
    with pytest.raises(ValidationError):
        ComposeEmailRequest(
            client_id=uuid.uuid4(),
            subject="s",
            message="m",
        )


def test_email_payload_and_open_email_response_carry_the_full_to_list():
    """
    The Sent/Message-Details display used to only ever read the single
    to_email field — a real display gap on top of the send-side bug,
    since even a correctly-persisted multi-recipient to_emails list
    would still only show its first entry. EmailPayload.to_emails (the
    persisted-payload shape) and OpenEmailResponse.to_emails (the API
    response shape) must both round-trip the full list.
    """

    from app.ticketing.schemas.open_email import OpenEmailResponse
    from app.ticketing.schemas.payloads.email_payload import EmailPayload

    payload = EmailPayload.model_validate(
        {
            "to_email": "a@example.com",
            "to_emails": ["a@example.com", "b@example.com", "c@example.com"],
            "subject": "s",
            "body": "m",
        }
    )
    assert payload.to_emails == ["a@example.com", "b@example.com", "c@example.com"]

    response = OpenEmailResponse(
        interaction_id=uuid.uuid4(),
        ticket_id=None,
        client_id=None,
        client_name="Unknown",
        to_email=payload.to_email,
        to_emails=payload.to_emails,
        from_email="support@example.com",
        from_name=None,
        cc=[],
        bcc=[],
        to_recipients=[],
        subject="s",
        body="m",
        message_id=None,
        received_at=datetime.now(timezone.utc).isoformat(),
        status="ASSIGNED",
        claimed_by=None,
        claimed_by_name=None,
        account_manager_name=None,
        ticket_priority=None,
        ticket_category=None,
        ticket_status=None,
        tags=[],
        folder_id=None,
        is_read=True,
        draft_message=None,
        draft_cc=[],
        draft_bcc=[],
        draft_attachments=[],
        replies=[],
        recommended_ticket_id=None,
        recommended_ticket_reason=None,
    )
    assert response.to_emails == ["a@example.com", "b@example.com", "c@example.com"]


def test_email_payload_to_emails_defaults_empty_for_inbound_or_legacy_rows():
    """A row stored before this field existed (or a genuine inbound email) must still deserialize, with an empty to_emails."""

    from app.ticketing.schemas.payloads.email_payload import EmailPayload

    payload = EmailPayload.model_validate({"to_email": "client@example.com", "subject": "s", "body": "m"})
    assert payload.to_emails == []

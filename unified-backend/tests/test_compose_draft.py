# test_compose_draft.py
#
# Regression coverage for Issue 3 (Compose drafts weren't saving
# reliably — ComposeView.tsx's "Save Draft" was 100% localStorage,
# because a brand-new Compose message had no interaction row for the
# real, server-backed draft endpoints to attach to). These cover the
# new sibling methods that give Compose a real draft: create_compose_
# draft/save_compose_draft/get_compose_draft/discard_compose_draft/
# send_compose_draft — a brand-new EMAIL-type Interaction row with
# parent_interaction_id=None and is_draft=True, distinct from the
# existing pre-ticket Reply-draft shape (a child row of a resolved
# thread root) which these deliberately never touch.
#
# Service-level, mocked InteractionRepository — same style as
# test_send_idempotency.py's own compose_email/send_draft coverage,
# since the actual dispatch/envelope machinery compose_email already
# owns is exercised by that file and by test_finalize_envelope_
# attachments.py, not re-tested here.

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.interaction import Interaction
from app.ticketing.schemas.compose import ComposeDraftSaveRequest, ComposeEmailResponse
from app.ticketing.services.interaction_service import InteractionService


def _build_service(interaction_repository, **kwargs):
    return InteractionService(
        interaction_repository=interaction_repository,
        ticket_repository=AsyncMock(),
        user_repository=AsyncMock(),
        client_repository=AsyncMock(),
        **kwargs,
    )


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


def _compose_draft_row(*, performed_by, payload=None, is_draft=True, parent=None, itype="EMAIL"):
    return Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type=itype,
        status=InteractionStatus.PENDING,
        direction=InteractionDirection.OUTBOUND,
        payload=payload or {"message": "", "cc": [], "bcc": [], "to_emails": []},
        performed_by=performed_by,
        parent_interaction_id=parent,
        is_draft=is_draft,
        is_visible=True,
        created_at=datetime.now(timezone.utc),
    )


async def test_create_compose_draft_creates_a_parentless_email_draft_row():
    repo = AsyncMock()
    current_user = _current_user()
    created = _compose_draft_row(performed_by=current_user.user_id)
    repo.create.return_value = created

    service = _build_service(repo)
    request = ComposeDraftSaveRequest(subject="Hello", message="World")

    response = await service.create_compose_draft(current_user=current_user, request=request)

    assert response.interaction_id == created.interaction_id
    create_call = repo.create.call_args.args[0]
    assert create_call.interaction_type == "EMAIL"
    assert create_call.parent_interaction_id is None
    assert create_call.is_draft is True
    assert create_call.payload["subject"] == "Hello"
    assert create_call.payload["message"] == "World"
    assert create_call.payload["dispatch_status"] == "DRAFT"


async def test_save_compose_draft_upserts_owned_draft_in_place():
    current_user = _current_user()
    draft = _compose_draft_row(performed_by=current_user.user_id)

    repo = AsyncMock()
    repo.get_by_id.return_value = draft
    updated = _compose_draft_row(
        performed_by=current_user.user_id,
        payload={"message": "Updated body", "cc": [], "bcc": [], "to_emails": ["a@example.com"]},
    )
    repo.update.return_value = updated

    service = _build_service(repo)
    service.attachment_repository = None
    service.storage_service = None

    request = ComposeDraftSaveRequest(
        message="Updated body", to_emails=["a@example.com"], subject="Re: test"
    )
    response = await service.save_compose_draft(
        interaction_id=draft.interaction_id, current_user=current_user, request=request
    )

    assert response.message == "Updated body"
    assert response.to_emails == ["a@example.com"]
    repo.update.assert_awaited_once()


async def test_get_owned_compose_draft_404s_for_a_reply_shaped_row():
    """
    A pre-ticket Reply draft (is_draft=True but with a real parent) or
    any non-EMAIL draft must never be reachable through the Compose
    draft methods — the two draft shapes are siblings, not one system.
    """

    current_user = _current_user()
    reply_draft = _compose_draft_row(
        performed_by=current_user.user_id, itype="REPLY", parent=uuid.uuid4()
    )

    repo = AsyncMock()
    repo.get_by_id.return_value = reply_draft

    service = _build_service(repo)

    with pytest.raises(HTTPException) as exc_info:
        await service._get_owned_compose_draft(reply_draft.interaction_id, current_user)
    assert exc_info.value.status_code == 404


async def test_get_owned_compose_draft_403s_for_a_different_users_draft():
    owner = _current_user()
    other = _current_user()
    draft = _compose_draft_row(performed_by=owner.user_id)

    repo = AsyncMock()
    repo.get_by_id.return_value = draft

    service = _build_service(repo)

    with pytest.raises(HTTPException) as exc_info:
        await service._get_owned_compose_draft(draft.interaction_id, other)
    assert exc_info.value.status_code == 403


async def test_discard_compose_draft_deletes_the_row():
    current_user = _current_user()
    draft = _compose_draft_row(performed_by=current_user.user_id)

    repo = AsyncMock()
    repo.get_by_id.return_value = draft

    service = _build_service(repo)
    service.attachment_repository = None
    service.storage_service = None

    response = await service.discard_compose_draft(draft.interaction_id, current_user)

    assert response.message == "Draft discarded."
    repo.delete_draft.assert_awaited_once_with(draft)


async def test_send_compose_draft_delegates_to_compose_email_and_cleans_up_the_draft(monkeypatch):
    """
    Mirrors send_draft's own established pattern (see
    test_send_idempotency.py's test_send_draft_threads_idempotency_
    key_into_add_interaction_reply): the actual send is delegated to
    the real compose_email, then the draft's attachments are
    reassigned onto the new message and the draft row is deleted.

    The pre-send deliverability re-check (its own dedicated test,
    below) is stubbed out here — this test is about delegation and
    cleanup, not validation.
    """

    async def _pass(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.ticketing.services.interaction_service.ensure_recipients_are_valid", _pass
    )

    current_user = _current_user()
    draft = _compose_draft_row(
        performed_by=current_user.user_id,
        payload={
            "client_id": str(uuid.uuid4()),
            "category_id": None,
            "to_email": "client@example.com",
            "to_emails": ["second@example.com"],
            "cc": [],
            "bcc": [],
            "subject": "Draft subject",
            "message": "Draft body",
            "body_html": None,
        },
    )

    repo = AsyncMock()
    repo.get_by_id.return_value = draft

    service = _build_service(repo)
    service.attachment_repository = AsyncMock()

    captured_requests = []

    async def _fake_compose_email(request, current_user, files=None, inline_image_interaction_ids=None, existing_attachment_source_interaction_id=None):
        captured_requests.append((request, existing_attachment_source_interaction_id))
        return ComposeEmailResponse(
            interaction_id=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
        )

    service.compose_email = _fake_compose_email

    response = await service.send_compose_draft(draft.interaction_id, current_user)

    assert isinstance(response, ComposeEmailResponse)
    assert len(captured_requests) == 1
    sent_request, source_id = captured_requests[0]
    assert sent_request.to_email == "client@example.com"
    assert sent_request.to_emails == ["second@example.com"]
    assert source_id == draft.interaction_id
    service.attachment_repository.reassign_interaction.assert_awaited_once_with(
        draft.interaction_id, response.interaction_id
    )
    repo.delete_draft.assert_awaited_once_with(draft)


async def test_send_compose_draft_validates_recipients_before_sending(monkeypatch):
    """
    A draft's stored addresses were only ever syntax-checked at save
    time (ComposeDraftSaveRequest's EmailStr fields) — send time must
    still re-validate deliverability, same as the compose route does
    for a normal (non-draft) send, and the whole send must be aborted
    (compose_email never called) if that check fails.
    """

    current_user = _current_user()
    draft = _compose_draft_row(
        performed_by=current_user.user_id,
        payload={
            "to_email": "someone@bad-domain.invalid",
            "to_emails": [],
            "cc": [],
            "bcc": [],
            "subject": "s",
            "message": "m",
        },
    )

    repo = AsyncMock()
    repo.get_by_id.return_value = draft

    service = _build_service(repo)
    service.compose_email = AsyncMock()

    async def _fail(*args, **kwargs):
        raise HTTPException(status_code=400, detail="not deliverable")

    monkeypatch.setattr(
        "app.ticketing.services.interaction_service.ensure_recipients_are_valid", _fail
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.send_compose_draft(draft.interaction_id, current_user)

    assert exc_info.value.status_code == 400
    service.compose_email.assert_not_called()
    repo.delete_draft.assert_not_called()


async def test_send_compose_draft_400s_when_no_from_client_or_category_was_chosen(monkeypatch):
    """
    A draft may legitimately have no "From" selected yet (unlike a
    real send, ComposeDraftSaveRequest never required one) — sending
    it before that's filled in must be a clean 400, not an unhandled
    pydantic ValidationError bubbling out of ComposeEmailRequest's own
    _require_exactly_one_sender validator.
    """

    async def _pass(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.ticketing.services.interaction_service.ensure_recipients_are_valid", _pass
    )

    current_user = _current_user()
    draft = _compose_draft_row(
        performed_by=current_user.user_id,
        payload={
            "client_id": None,
            "category_id": None,
            "to_email": "someone@example.com",
            "to_emails": [],
            "cc": [],
            "bcc": [],
            "subject": "s",
            "message": "m",
        },
    )

    repo = AsyncMock()
    repo.get_by_id.return_value = draft

    service = _build_service(repo)
    service.compose_email = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await service.send_compose_draft(draft.interaction_id, current_user)

    assert exc_info.value.status_code == 400
    service.compose_email.assert_not_called()

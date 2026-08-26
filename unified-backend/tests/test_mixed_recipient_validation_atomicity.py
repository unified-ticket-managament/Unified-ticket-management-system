# test_mixed_recipient_validation_atomicity.py
#
# Regression coverage for Issue 7 (HIGH PRIORITY): if any recipient
# across To/Cc/Bcc is invalid, the send must be entirely rejected —
# never a partial send to just the valid address(es). Investigated and
# found already correct: ensure_recipients_are_valid (recipient_
# validation.py) validates every address concurrently via asyncio.
# gather, which re-raises the first failure and aborts the whole call.
# test_outgoing_mail_service_recipient_validation.py already covers
# OutgoingMailService's own atomicity, and Forward's is covered by
# test_forward_to_internal_user.py. This file covers add_reply
# (ticket) and add_interaction_reply (pre-ticket), which validate
# internally and didn't yet have a dedicated "zero rows created on a
# mixed valid/invalid set" test.
#
# compose_email is deliberately NOT tested the same way here: unlike
# the two methods above, it does not call ensure_recipients_are_valid
# itself — that validation happens one layer up, in the compose route
# (api/inbox.py), before ComposeEmailRequest is ever constructed (its
# EmailStr-typed fields would otherwise raise an unhandled pydantic.
# ValidationError instead of a clean 400 — see that route's own
# comment). Calling service.compose_email() directly, as a unit test
# would, bypasses that route entirely and proves nothing about the
# real endpoint's atomicity. The one caller that constructs
# ComposeEmailRequest without going through that route — send_compose_
# draft — was given its own explicit ensure_recipients_are_valid call
# for exactly this reason (see interaction_service.py and this same
# guarantee's own test, test_send_compose_draft_validates_recipients_
# before_sending, in test_compose_draft.py). What's tested below
# instead is the exact merged-recipient-list shape the compose route
# builds (to_email + to_emails, the to_emails field TODO 5 added) to
# confirm that combined list is still rejected atomically when mixed.
#
# A real, proven-nonexistent domain (the same one test_recipient_
# validation.py's own test_rejects_a_domain_that_does_not_exist uses)
# is used for "invalid" rather than a mock, so this exercises the real
# deliverability check end to end.

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.ticketing.models.interaction import Interaction
from app.ticketing.schemas.compose import ComposeEmailRequest
from app.ticketing.schemas.ticket_action import InteractionReplyRequest, ReplyCreate
from app.ticketing.services.interaction_service import InteractionService

VALID_DOMAIN_ADDRESS = "someone@painmedpa.com"
# The exact same proven-reliably-nonexistent domain test_recipient_
# validation.py's own test_rejects_a_domain_that_does_not_exist uses
# (a typo'd TLD of this product's real mail domain) — a made-up-but-
# plausible .com domain was tried first here and turned out to
# actually resolve in this environment (some networks wildcard-
# resolve any nonexistent domain), so this reuses the one address
# already confirmed to genuinely have no DNS presence rather than
# risking the same flakiness again.
INVALID_DOMAIN_ADDRESS = "someone@painmedpa.cm"


def _current_user() -> SimpleNamespace:
    return SimpleNamespace(
        user_id=uuid.uuid4(),
        name="Agent",
        role=SimpleNamespace(name="Staff"),
        permissions=["communication:reply_external", "ticket:reply", "ticket:editown_ticket"],
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


def _build_compose_service():
    repo = AsyncMock()
    repo.get_by_idempotency_key.return_value = None
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
    return service, repo, fake_client


# ---------------------------------------------------------------
# The compose route's own merged-recipient-list validation shape —
# see this file's header comment for why compose_email itself (the
# service method) is not the right place to test this.
# ---------------------------------------------------------------

from app.ticketing.utils.recipient_validation import ensure_recipients_are_valid


@pytest.mark.parametrize(
    "to_email,to_emails,cc,bcc",
    [
        pytest.param(VALID_DOMAIN_ADDRESS, [INVALID_DOMAIN_ADDRESS], [], [], id="valid-to+invalid-to"),
        pytest.param(INVALID_DOMAIN_ADDRESS, [], [], [], id="invalid-to-only"),
        pytest.param(VALID_DOMAIN_ADDRESS, [], [INVALID_DOMAIN_ADDRESS], [], id="valid-to+invalid-cc"),
        pytest.param(VALID_DOMAIN_ADDRESS, [], [], [INVALID_DOMAIN_ADDRESS], id="valid-to+invalid-bcc"),
        pytest.param(
            VALID_DOMAIN_ADDRESS,
            [VALID_DOMAIN_ADDRESS.replace("someone", "someone2")],
            [INVALID_DOMAIN_ADDRESS],
            [],
            id="multiple-valid+one-invalid",
        ),
    ],
)
async def test_compose_route_merged_recipient_list_rejects_atomically(to_email, to_emails, cc, bcc):
    """
    Mirrors api/inbox.py's compose route exactly: to=([to_email] if
    to_email else []) + to_emails, validated together with cc/bcc in
    one ensure_recipients_are_valid call, before ComposeEmailRequest
    is ever constructed.
    """

    with pytest.raises(HTTPException) as exc_info:
        await ensure_recipients_are_valid(
            to=([to_email] if to_email else []) + list(to_emails), cc=cc, bcc=bcc
        )

    assert exc_info.value.status_code == 400


async def test_compose_email_sends_when_all_recipients_are_valid(monkeypatch):
    service, repo, fake_client = _build_compose_service()

    async def _pass(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.ticketing.services.interaction_service.ensure_recipients_are_valid", _pass
    )

    def _echo_create(data):
        return Interaction(
            interaction_id=uuid.uuid4(), created_at=datetime.now(timezone.utc), **data.model_dump()
        )

    repo.create.side_effect = _echo_create

    async def _no_dl_members(*args, **kwargs):
        return []

    from app.ticketing.services import interaction_service as module

    monkeypatch.setattr(module, "resolve_distribution_list_emails", _no_dl_members)

    request = ComposeEmailRequest(
        client_id=fake_client.client_id,
        subject="Test",
        message="Hello",
        to_email=VALID_DOMAIN_ADDRESS,
        cc=[VALID_DOMAIN_ADDRESS.replace("someone", "cc-person")],
    )

    await service.compose_email(request=request, current_user=_current_user())
    repo.create.assert_called_once()


# ---------------------------------------------------------------
# add_reply (ticket reply) — mocked ticket/repository, same style as
# test_send_idempotency.py's own compose_email/send_draft coverage.
# ---------------------------------------------------------------


def _fake_ticket():
    return SimpleNamespace(
        ticket_id=uuid.uuid4(),
        current_status="IN_PROGRESS",
        agent_id=None,
        client_company_id=None,
    )


async def test_add_reply_rejects_entirely_on_mixed_valid_invalid_cc(monkeypatch):
    ticket_repo = AsyncMock()
    ticket = _fake_ticket()
    ticket_repo.get_by_id.return_value = ticket

    interaction_repo = AsyncMock()
    interaction_repo.get_latest_inbound_email_for_ticket.return_value = None

    service = InteractionService(
        interaction_repository=interaction_repo,
        ticket_repository=ticket_repo,
        user_repository=AsyncMock(),
        client_repository=AsyncMock(),
        distribution_list_repository=AsyncMock(),
    )

    current_user = _current_user()
    current_user.role = SimpleNamespace(name="Staff")

    # ensure_agent_can_act_on_ticket's own category-visibility branch
    # would otherwise need real category relationships loaded on this
    # plain SimpleNamespace user — side-stepped here since this test
    # is about recipient-validation atomicity, not authorization
    # (already covered by test_ticket_draft.py's real-DB tests).
    monkeypatch.setattr(
        "app.ticketing.services.interaction_service.ensure_agent_can_act_on_ticket",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.ticketing.services.interaction_service.ensure_account_manager_owns_ticket_client",
        AsyncMock(return_value=None),
    )

    request = ReplyCreate(
        message="Hello client",
        to_email=VALID_DOMAIN_ADDRESS,
        cc=[INVALID_DOMAIN_ADDRESS],
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.add_reply(ticket.ticket_id, request, current_user)

    assert exc_info.value.status_code == 400
    interaction_repo.create.assert_not_called()


# ---------------------------------------------------------------
# add_interaction_reply (pre-ticket reply)
# ---------------------------------------------------------------


async def test_add_interaction_reply_rejects_entirely_on_mixed_valid_invalid_bcc(monkeypatch):
    root = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        direction="INBOUND",
        status="PENDING",
        payload={},
        ticket_id=None,
        client_id=None,
        created_at=datetime.now(timezone.utc),
    )

    interaction_repo = AsyncMock()
    interaction_repo.get_by_id.return_value = root
    interaction_repo.find_thread_root.return_value = root
    interaction_repo.get_by_idempotency_key.return_value = None

    service = InteractionService(
        interaction_repository=interaction_repo,
        ticket_repository=AsyncMock(),
        user_repository=AsyncMock(),
        client_repository=AsyncMock(),
        distribution_list_repository=AsyncMock(),
    )

    # Instance-method override, not a module-level monkeypatch — this
    # is a bound method on the service (InteractionService._ensure_
    # can_act_on_pending_interaction), so overriding the module
    # attribute wouldn't reach it. This test is about recipient-
    # validation atomicity, not pending-interaction authorization
    # (unrelated, already covered elsewhere).
    service._ensure_can_act_on_pending_interaction = AsyncMock(return_value=None)

    current_user = _current_user()

    request = InteractionReplyRequest(
        message="Hello client",
        to_email=VALID_DOMAIN_ADDRESS,
        bcc=[INVALID_DOMAIN_ADDRESS],
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.add_interaction_reply(root.interaction_id, request, current_user)

    assert exc_info.value.status_code == 400
    interaction_repo.create.assert_not_called()

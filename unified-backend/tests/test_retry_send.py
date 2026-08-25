# test_retry_send.py
#
# Service-level coverage for P1 item 5 (manual Retry Send) — exercises
# InteractionService.retry_failed_send against a fully mocked
# InteractionRepository. The real concurrency-safety mechanism
# (try_transition_to_pending_send's conditional UPDATE) already has
# its own real-DB coverage in test_out_of_order_threading.py
# (test_try_transition_to_pending_send_*); this file focuses on the
# service-layer orchestration around it — authorization, envelope
# reuse, and the concurrent-retry rejection path.

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.ticketing.enums import InteractionDirection, InteractionStatus, TicketStatus
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.ticket import Ticket
from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services.interaction_service import InteractionService


def _envelope_payload() -> dict:
    return OutboundEnvelope(
        from_email="clientinbox@example.com",
        to_email="patient@example.com",
        subject="Re: Test",
        message_id="<msg@example.com>",
        body="Hello.",
    ).model_dump()


def _failed_interaction(*, performed_by, envelope=True) -> Interaction:
    payload = {"message": "Hello.", "dispatch_status": "FAILED", "dispatch_error": "boom"}
    if envelope:
        payload["envelope"] = _envelope_payload()
    return Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="REPLY",
        status=InteractionStatus.ASSIGNED,
        direction=InteractionDirection.OUTBOUND,
        payload=payload,
        performed_by=performed_by,
        dispatch_status="FAILED",
        dispatch_error="boom",
        ticket_id=None,
        created_at=datetime.now(timezone.utc),
    )


def _build_service(repo):
    return InteractionService(
        interaction_repository=repo,
        ticket_repository=AsyncMock(),
        user_repository=AsyncMock(),
    )


async def test_retry_failed_send_reuses_the_persisted_envelope_and_reschedules():
    user_id = uuid.uuid4()
    failed = _failed_interaction(performed_by=user_id)

    repo = AsyncMock()
    repo.get_by_id.return_value = failed
    repo.try_transition_to_pending_send.return_value = failed

    service = _build_service(repo)
    service._schedule_delayed_send = AsyncMock()

    current_user = AsyncMock()
    current_user.user_id = user_id

    response = await service.retry_failed_send(
        interaction_id=failed.interaction_id, current_user=current_user
    )

    assert response.interaction_id == failed.interaction_id
    repo.try_transition_to_pending_send.assert_awaited_once_with(failed.interaction_id)

    # The envelope handed to the real dispatch path must be the exact
    # one persisted at creation time — never rebuilt from request data
    # (there is no request here at all, only the stored payload).
    service._schedule_delayed_send.assert_awaited_once()
    called_interaction, called_envelope = service._schedule_delayed_send.call_args.args
    assert called_interaction is failed
    assert isinstance(called_envelope, OutboundEnvelope)
    assert called_envelope.model_dump() == _envelope_payload()

    # payload's own dispatch_status mirror is kept in sync with the
    # real column the CAS already flipped — the same dual-write
    # convention every other dispatch-state transition follows.
    repo.update.assert_awaited()
    update_call = repo.update.call_args
    assert update_call.args[0] is failed


async def test_retry_failed_send_404s_when_interaction_missing():
    repo = AsyncMock()
    repo.get_by_id.return_value = None
    service = _build_service(repo)

    current_user = AsyncMock()
    current_user.user_id = uuid.uuid4()

    with pytest.raises(HTTPException) as exc_info:
        await service.retry_failed_send(interaction_id=uuid.uuid4(), current_user=current_user)

    assert exc_info.value.status_code == 404


async def test_retry_failed_send_403s_for_a_different_user():
    failed = _failed_interaction(performed_by=uuid.uuid4())
    repo = AsyncMock()
    repo.get_by_id.return_value = failed
    service = _build_service(repo)

    current_user = AsyncMock()
    current_user.user_id = uuid.uuid4()  # a different user

    with pytest.raises(HTTPException) as exc_info:
        await service.retry_failed_send(
            interaction_id=failed.interaction_id, current_user=current_user
        )

    assert exc_info.value.status_code == 403
    repo.try_transition_to_pending_send.assert_not_called()


async def test_retry_failed_send_400s_when_no_envelope_was_ever_attempted():
    user_id = uuid.uuid4()
    failed = _failed_interaction(performed_by=user_id, envelope=False)
    repo = AsyncMock()
    repo.get_by_id.return_value = failed
    service = _build_service(repo)

    current_user = AsyncMock()
    current_user.user_id = user_id

    with pytest.raises(HTTPException) as exc_info:
        await service.retry_failed_send(
            interaction_id=failed.interaction_id, current_user=current_user
        )

    assert exc_info.value.status_code == 400
    repo.try_transition_to_pending_send.assert_not_called()


async def test_concurrent_retry_loses_the_cas_and_400s_without_a_second_dispatch():
    """Two simultaneous Retry Send clicks: the CAS guard
    (try_transition_to_pending_send) is what actually prevents a
    duplicate send — simulated here by the repository returning None
    (as it would for the second caller once the first has already
    flipped dispatch_status off FAILED)."""

    user_id = uuid.uuid4()
    failed = _failed_interaction(performed_by=user_id)
    repo = AsyncMock()
    repo.get_by_id.return_value = failed
    repo.try_transition_to_pending_send.return_value = None  # lost the race

    service = _build_service(repo)
    service._schedule_delayed_send = AsyncMock()

    current_user = AsyncMock()
    current_user.user_id = user_id

    with pytest.raises(HTTPException) as exc_info:
        await service.retry_failed_send(
            interaction_id=failed.interaction_id, current_user=current_user
        )

    assert exc_info.value.status_code == 400
    service._schedule_delayed_send.assert_not_called()


async def test_retry_failed_send_400s_when_the_ticket_has_since_been_closed(monkeypatch):
    """
    P2 regression guard: retry_failed_send used to skip every
    ticket-state guard the original send enforces (ensure_ticket_not_
    closed/ensure_agent_can_act_on_ticket/ensure_account_manager_owns_
    ticket_client) — a ticket closed *after* the original send failed
    but *before* the agent clicked Retry would still re-dispatch a
    real email. Bypass the other two guards here (separately covered
    elsewhere) to isolate the closed-ticket check specifically.
    """
    import app.ticketing.services.interaction_service as interaction_service_module

    monkeypatch.setattr(
        interaction_service_module, "ensure_agent_can_act_on_ticket", AsyncMock()
    )
    monkeypatch.setattr(
        interaction_service_module, "ensure_account_manager_owns_ticket_client", AsyncMock()
    )

    user_id = uuid.uuid4()
    ticket_id = uuid.uuid4()
    failed = _failed_interaction(performed_by=user_id)
    failed.ticket_id = ticket_id

    closed_ticket = Ticket(ticket_id=ticket_id, current_status=TicketStatus.CLOSED)

    repo = AsyncMock()
    repo.get_by_id.return_value = failed
    service = _build_service(repo)
    service.ticket_repository.get_by_id = AsyncMock(return_value=closed_ticket)

    current_user = AsyncMock()
    current_user.user_id = user_id

    with pytest.raises(HTTPException) as exc_info:
        await service.retry_failed_send(
            interaction_id=failed.interaction_id, current_user=current_user
        )

    assert exc_info.value.status_code == 400
    repo.try_transition_to_pending_send.assert_not_called()

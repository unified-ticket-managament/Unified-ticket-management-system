# test_outgoing_mail_service_recipient_validation.py
#
# P1 regression guard: POST /api/mail/outgoing (OutgoingMailService.
# send_email) used to call mail_provider_client.send_email directly
# with zero recipient validation beyond Pydantic's own EmailStr syntax
# check — every other outbound path (Compose/Reply/Reply-All/Forward)
# runs the shared deliverability-aware ensure_recipients_are_valid
# check first. Verifies (a) a validation failure raises before any
# provider call is ever made — no partially-sent message — and (b) a
# passing validation still dispatches normally. Mocks
# ensure_recipients_are_valid itself rather than hitting real DNS,
# matching this module's own "only explicitly domain-focused tests
# make a real DNS query" convention (see test_recipient_validation.py).

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.ticketing.schemas.mail_integration import OutgoingEmailRequest
from app.ticketing.services import outgoing_mail_service as outgoing_mail_service_module
from app.ticketing.services.outgoing_mail_service import OutgoingMailService

# Phase 2C added a required current_user parameter to send_email (used
# only by the client_id branch's ensure_can_compose_for_client check —
# see test_outgoing_mail_client_id_authorization.py for that
# coverage). Every request built by _request() below omits client_id,
# so ensure_can_compose_for_client itself is never reached — but Phase
# 2E (BD-16 interim mitigation) added a real role check to the
# from_email branch these tests DO exercise, so the placeholder now
# needs a role that passes it (Super Admin, one of the two allowed) —
# these tests are about recipient validation, not this authorization
# boundary, and shouldn't be blocked by it.
_UNUSED_ACTOR = SimpleNamespace(role=SimpleNamespace(name="Super Admin"))


def _request(**overrides) -> OutgoingEmailRequest:
    base = dict(
        from_email="sender@painmedpa.com",
        to_email="patient@example.com",
        cc=[],
        bcc=[],
        subject="Hello",
        body="Hi there.",
    )
    base.update(overrides)
    return OutgoingEmailRequest(**base)


async def test_send_email_never_dispatches_when_recipient_validation_fails(monkeypatch):
    validate = AsyncMock(side_effect=HTTPException(status_code=400, detail="bad domain"))
    monkeypatch.setattr(outgoing_mail_service_module, "ensure_recipients_are_valid", validate)

    mail_provider_client = AsyncMock()
    service = OutgoingMailService(
        client_repository=AsyncMock(), mail_provider_client=mail_provider_client
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.send_email(_request(), _UNUSED_ACTOR)

    assert exc_info.value.status_code == 400
    mail_provider_client.send_email.assert_not_called()


async def test_send_email_dispatches_once_recipient_validation_passes(monkeypatch):
    validate = AsyncMock(return_value=None)
    monkeypatch.setattr(outgoing_mail_service_module, "ensure_recipients_are_valid", validate)

    mail_provider_client = AsyncMock()
    mail_provider_client.send_email.return_value = AsyncMock(
        provider_message_id="mock-1", status="SENT"
    )
    service = OutgoingMailService(
        client_repository=AsyncMock(), mail_provider_client=mail_provider_client
    )

    request = _request(cc=["cc@example.com"], bcc=["bcc@example.com"])
    await service.send_email(request, _UNUSED_ACTOR)

    validate.assert_awaited_once_with(
        to=request.to_email, cc=request.cc, bcc=request.bcc
    )
    mail_provider_client.send_email.assert_awaited_once()

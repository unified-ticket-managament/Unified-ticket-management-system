# test_outbound_dispatcher.py
#
# Pure-logic coverage for OutboundDispatcher — no DB, no real network
# call. Verifies the seam every real send path (Reply, Reply-All,
# Forward-via-Compose, Draft-Send) now goes through actually calls the
# configured MailProviderClient and translates its outcome into either
# a real MailProviderSendResult or an OutboundDispatchError, which is
# the one thing interaction_service.py's _dispatch_and_record needs to
# tell "sent" from "failed."

from uuid import uuid4

import pytest

from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services.mail_provider import MailProviderSendResult
from app.ticketing.services.outbound_dispatcher import OutboundDispatchError, OutboundDispatcher


def _envelope() -> OutboundEnvelope:
    return OutboundEnvelope(
        from_email="clientinbox@example.com",
        to_email="patient@example.com",
        subject="Re: Test",
        message_id="<id@example.com>",
        body="Hello.",
    )


class _StubSucceedingClient:
    async def send_email(self, envelope):
        return MailProviderSendResult(provider_message_id="graph-msg-123", status="SENT")


class _StubFailingClient:
    async def send_email(self, envelope):
        raise RuntimeError("Graph API error 500: something broke")


async def test_dispatch_returns_result_on_success(monkeypatch):
    monkeypatch.setattr(
        "app.ticketing.services.outbound_dispatcher.get_mail_provider_client",
        lambda: _StubSucceedingClient(),
    )

    dispatcher = OutboundDispatcher()
    result = await dispatcher.dispatch(uuid4(), _envelope())

    assert isinstance(result, MailProviderSendResult)
    assert result.provider_message_id == "graph-msg-123"
    assert result.status == "SENT"


async def test_dispatch_raises_outbound_dispatch_error_on_failure(monkeypatch):
    monkeypatch.setattr(
        "app.ticketing.services.outbound_dispatcher.get_mail_provider_client",
        lambda: _StubFailingClient(),
    )

    dispatcher = OutboundDispatcher()

    with pytest.raises(OutboundDispatchError) as exc_info:
        await dispatcher.dispatch(uuid4(), _envelope())

    assert "something broke" in str(exc_info.value)

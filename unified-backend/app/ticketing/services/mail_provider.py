# mail_provider.py
#
# The mail-transport seam. Everything upstream (OutgoingMailService,
# the /api/mail/outgoing and /api/mail/incoming routes) talks to this
# interface only — never to a concrete provider — so swapping the mock
# below for the real Microsoft Graph client (graph_client.py) is a
# one-function change (get_mail_provider_client() below), not a
# rewrite of any caller.

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.ticketing.schemas.mail_integration import (
    GraphEmailAddress,
    GraphItemBody,
    GraphRecipient,
    IncomingMailPayload,
)
from app.ticketing.schemas.payloads import OutboundEnvelope

logger = logging.getLogger(__name__)


class MailProviderSendResult(BaseModel):
    provider_message_id: str
    status: str


class MailProviderClient(ABC):
    """
    The provider-agnostic contract every mail transport implements.
    `send_email` backs outbound send (POST /api/mail/outgoing);
    `fetch_message` backs the inbound webhook path (POST
    /api/mail/incoming) — a real Graph change notification only
    carries a message id, so the receiving route calls this to
    retrieve the actual content before handing it to
    EmailService.receive_email; `list_new_messages` backs the
    polling-based inbound path (graph_mail_poller.py) — a
    webhook-free alternative that this app initiates itself rather
    than waiting for Graph to call back, useful wherever a public
    HTTPS notification URL isn't available (e.g. local dev with no
    tunnel). See graph_client.py for the real implementation and
    mail_integration.py / graph_mail_poller.py for the call sites.
    """

    @abstractmethod
    async def send_email(self, envelope: OutboundEnvelope) -> MailProviderSendResult:
        raise NotImplementedError

    @abstractmethod
    async def fetch_message(self, message_id: str) -> IncomingMailPayload:
        raise NotImplementedError

    @abstractmethod
    async def list_new_messages(self, since: datetime) -> list[IncomingMailPayload]:
        raise NotImplementedError


class MockMailProviderClient(MailProviderClient):
    """
    Stands in for a real provider until Microsoft Graph credentials
    exist. Never makes a network call — just logs and fabricates a
    successful result, so the rest of the system (routers, services,
    response schemas) can be built and tested end-to-end today, and
    so local/CI environments with no Azure app registration keep
    working exactly as before this module gained a real Graph option.
    """

    async def send_email(self, envelope: OutboundEnvelope) -> MailProviderSendResult:
        provider_message_id = f"mock-{uuid4().hex}"

        logger.info(
            "mock provider send: provider_message_id=%s message_id=%s to=%s subject=%r",
            provider_message_id,
            envelope.message_id,
            envelope.to_email,
            envelope.subject,
        )

        return MailProviderSendResult(
            provider_message_id=provider_message_id,
            status="SENT",
        )

    async def fetch_message(self, message_id: str) -> IncomingMailPayload:
        logger.info("mock provider fetch_message: message_id=%s", message_id)

        return IncomingMailPayload(
            internetMessageId=f"<mock-{uuid4().hex}@example.com>",
            subject="(mock message — no Microsoft Graph mailbox configured)",
            from_=GraphRecipient(
                emailAddress=GraphEmailAddress(
                    name="Mock Sender", address="mock-sender@example.com"
                )
            ),
            toRecipients=[
                GraphRecipient(
                    emailAddress=GraphEmailAddress(address="mock-inbox@example.com")
                )
            ],
            body=GraphItemBody(
                contentType="text",
                content=(
                    "This is a mocked message body — GRAPH_TENANT_ID/GRAPH_CLIENT_ID/"
                    "GRAPH_CLIENT_SECRET/GRAPH_MAILBOX_ADDRESS are not all configured, "
                    "so no real Microsoft Graph mailbox was queried."
                ),
            ),
        )

    async def list_new_messages(self, since: datetime) -> list[IncomingMailPayload]:
        logger.debug("mock provider list_new_messages: since=%s (returning none)", since)

        # Deliberately empty, not a fabricated message list — unlike
        # send_email/fetch_message, a poll tick running forever against
        # fake data would be a real (if harmless) surprise the first
        # time someone actually watches the logs during local testing.
        return []


def get_mail_provider_client(settings: Settings | None = None) -> MailProviderClient:
    """
    Dependency-injection swap point. Returns a real GraphMailProviderClient
    once graph_tenant_id/graph_client_id/graph_client_secret/
    graph_mailbox_address are all set (see config.py) — MockMailProviderClient
    otherwise. No caller needs to change when real credentials are added;
    only Settings/.env does.

    Imports graph_client/graph_auth lazily (function-local, not
    module-level) to avoid a circular import: graph_client.py imports
    MailProviderClient/MailProviderSendResult from this module.
    """

    settings = settings or get_settings()

    from app.ticketing.services.graph_auth import build_graph_auth_client
    from app.ticketing.services.graph_client import build_graph_mail_provider_client

    auth_client = build_graph_auth_client(settings)
    graph_client = build_graph_mail_provider_client(settings, auth_client)

    if graph_client is not None:
        return graph_client

    return MockMailProviderClient()

# mail_provider.py
#
# The mail-transport seam. Everything upstream (OutgoingMailService,
# the /api/mail/outgoing route) talks to this interface only — never
# to a concrete provider — so swapping the mock below for a real
# Microsoft Graph client later is a one-class change, not a rewrite.

import logging
from abc import ABC, abstractmethod
from uuid import uuid4

from pydantic import BaseModel

from app.ticketing.schemas.payloads import OutboundEnvelope

logger = logging.getLogger(__name__)


class MailProviderSendResult(BaseModel):
    provider_message_id: str
    status: str


class MailProviderClient(ABC):
    """
    The provider-agnostic contract every mail transport implements.
    `send_email` is the only method needed today; a future
    `fetch_incoming_emails`-style method (for a polling, rather than
    webhook-push, Graph integration) can be added here later without
    touching any call site.
    """

    @abstractmethod
    async def send_email(self, envelope: OutboundEnvelope) -> MailProviderSendResult:
        raise NotImplementedError


class MockMailProviderClient(MailProviderClient):
    """
    Stands in for a real provider until Microsoft Graph credentials
    exist. Never makes a network call — just logs the envelope and
    fabricates a successful result, so the rest of the system
    (routers, services, response schemas) can be built and tested
    end-to-end today.
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

        # ============================================================
        # FUTURE MICROSOFT GRAPH INTEGRATION POINT
        # ------------------------------------------------------------
        # Replace this method's body (or swap this whole class for a
        # GraphMailProviderClient implementing the same
        # MailProviderClient interface) with a real call to
        # POST /users/{mailbox}/sendMail via the Microsoft Graph SDK,
        # authenticated through MSAL client-credentials flow once an
        # Azure AD app registration and tenant credentials exist.
        # Do NOT implement that authentication yet — this class must
        # keep working as the default until credentials are available.
        # ============================================================

        return MailProviderSendResult(
            provider_message_id=provider_message_id,
            status="SENT",
        )


def get_mail_provider_client() -> MailProviderClient:
    """
    Dependency-injection swap point. Returns the mock today; once
    Graph credentials exist, change this single function to return a
    GraphMailProviderClient instead — no caller needs to change.
    """

    return MockMailProviderClient()

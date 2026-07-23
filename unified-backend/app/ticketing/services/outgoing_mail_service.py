# outgoing_mail_service.py
#
# Backs POST /api/mail/outgoing — the standalone "send this email
# through the provider" primitive. Deliberately decoupled from
# ticket/interaction bookkeeping: ticket-linked sends continue to go
# through the existing reply/compose flows
# (InteractionService.add_reply / compose_email), which build their
# own OutboundEnvelope the same way and remain untouched by this
# module. This service exists to exercise and expose the
# MailProviderClient seam directly, ready for Microsoft Graph to be
# plugged in behind it.

from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import get_settings
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.schemas.mail_integration import (
    OutgoingEmailRequest,
    OutgoingEmailResponse,
)
from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services.email_envelope import build_compose_envelope
from app.ticketing.services.email_service import resolve_shared_mailbox_address
from app.ticketing.services.mail_provider import MailProviderClient


def _generate_message_id(from_email: str) -> str:
    domain = from_email.split("@", 1)[-1] or "probeps.com"
    return f"<{uuid4().hex}@{domain}>"


class OutgoingMailService:
    def __init__(
        self,
        client_repository: ClientRepository,
        mail_provider_client: MailProviderClient,
    ):
        self.client_repository = client_repository
        self.mail_provider_client = mail_provider_client

    async def send_email(self, request: OutgoingEmailRequest) -> OutgoingEmailResponse:
        envelope = await self._build_envelope(request)

        result = await self.mail_provider_client.send_email(envelope)

        return OutgoingEmailResponse(
            message="Email dispatched successfully (mocked — Microsoft Graph integration pending).",
            provider_message_id=result.provider_message_id,
            status=result.status,
            dispatched_at=datetime.now(timezone.utc),
            envelope=envelope,
        )

    async def _build_envelope(self, request: OutgoingEmailRequest) -> OutboundEnvelope:
        if request.client_id is not None:
            client = await self.client_repository.get_by_id(request.client_id)

            if client is None:
                raise ValueError("Client not found.")

            # Reuses the same envelope builder Compose already uses,
            # so the "From is always the shared support mailbox"
            # invariant is enforced in exactly one place. `client` is
            # only used to validate request.client_id here — the From
            # address itself comes from the shared mailbox, never
            # Client.inbox_email (the client's own address).
            return build_compose_envelope(
                from_email=resolve_shared_mailbox_address(get_settings()),
                to_email=request.to_email,
                subject=request.subject,
                body=request.body,
                cc=request.cc,
                bcc=request.bcc,
            )

        # request.from_email is guaranteed set here by
        # OutgoingEmailRequest's model validator.
        return OutboundEnvelope(
            from_email=request.from_email,
            from_name=request.from_name,
            to_email=request.to_email,
            cc=request.cc,
            bcc=request.bcc,
            subject=request.subject,
            message_id=_generate_message_id(request.from_email),
            in_reply_to=None,
            references=[],
            body=request.body,
        )

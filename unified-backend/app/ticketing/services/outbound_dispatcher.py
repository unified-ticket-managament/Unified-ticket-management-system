# outbound_dispatcher.py

import logging
from uuid import UUID

from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services.mail_provider import MailProviderSendResult, get_mail_provider_client

logger = logging.getLogger(__name__)


class OutboundDispatchError(Exception):
    """
    Raised when dispatch() fails to actually send — wraps whatever the
    underlying MailProviderClient raised (GraphAPIError, GraphAuthError,
    a network timeout, ...) into one type callers can catch regardless
    of which provider (Graph today, a future one later, or the mock)
    is configured. Callers should treat this the same way any other
    "the reply wasn't delivered" failure is surfaced to the agent.
    """


class OutboundDispatcher:
    """
    The seam every real send path (Reply, the Reply-All-flavored Reply,
    Forward-via-Compose, Draft-Send) already calls after building an
    OutboundEnvelope and persisting the interaction. Delegates to
    get_mail_provider_client() — the same factory that already returns
    a real GraphMailProviderClient once Graph credentials are
    configured, MockMailProviderClient otherwise — so this class needs
    no provider-specific knowledge of its own.

    Every caller already stores `payload.dispatch_status = "QUEUED"`
    before calling dispatch(); callers are responsible for updating
    that to "SENT" (using this method's returned provider_message_id)
    on success, or "FAILED" on an OutboundDispatchError, since only the
    caller has the Interaction row and DB session in scope.
    """

    async def dispatch(
        self, interaction_id: UUID, envelope: OutboundEnvelope
    ) -> MailProviderSendResult:
        mail_provider_client = get_mail_provider_client()

        try:
            result = await mail_provider_client.send_email(envelope)
        except Exception as exc:
            logger.exception(
                "outbound dispatch failed: interaction_id=%s message_id=%s to=%s subject=%r",
                interaction_id,
                envelope.message_id,
                envelope.to_email,
                envelope.subject,
            )
            raise OutboundDispatchError(str(exc)) from exc

        logger.info(
            "outbound dispatch succeeded: interaction_id=%s message_id=%s to=%s "
            "subject=%r provider_message_id=%s",
            interaction_id,
            envelope.message_id,
            envelope.to_email,
            envelope.subject,
            result.provider_message_id,
        )

        return result

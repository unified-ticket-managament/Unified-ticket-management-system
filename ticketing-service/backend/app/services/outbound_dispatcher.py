# outbound_dispatcher.py

import logging
from uuid import UUID

from app.schemas.payloads import OutboundEnvelope

logger = logging.getLogger(__name__)


class OutboundDispatcher:
    """
    The seam Task 1's transport layer plugs into. For now this is a
    no-op that only logs — nothing actually leaves the platform yet.

    Every reply is stored with `payload.dispatch_status = "QUEUED"`
    regardless of what this does; Task 1 replaces `dispatch()` with
    real SMTP/API delivery and is responsible for updating that
    status to SENT or FAILED once it does.
    """

    async def dispatch(self, interaction_id: UUID, envelope: OutboundEnvelope) -> None:
        logger.info(
            "queued outbound email: interaction_id=%s message_id=%s to=%s subject=%r",
            interaction_id,
            envelope.message_id,
            envelope.to_email,
            envelope.subject,
        )

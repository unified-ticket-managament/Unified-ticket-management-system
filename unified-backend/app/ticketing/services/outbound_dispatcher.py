# outbound_dispatcher.py

import logging
from uuid import UUID

from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services.mail_provider import MailProviderSendResult, get_mail_provider_client
from app.ticketing.storage import get_storage_service
from app.ticketing.storage.base import StorageConfigurationError

logger = logging.getLogger(__name__)


class OutboundDispatchError(Exception):
    """
    Raised when dispatch() fails to actually send — wraps whatever the
    underlying MailProviderClient raised (GraphAPIError, GraphAuthError,
    a network timeout, ...) into one type callers can catch regardless
    of which provider (Graph today, a future one later, or the mock)
    is configured. Callers should treat this the same way any other
    "the reply wasn't delivered" failure is surfaced to the agent.

    `operation`/`status_code`/`orphaned_provider_draft_id` (Phase 2
    hardening) are populated, via getattr with a safe None default,
    from whatever the underlying exception happened to carry (today,
    only GraphAPIError does) — additive observability, never required.
    A caller (InteractionService._dispatch_and_record) uses these to
    store a more specific dispatch_error than a bare string, and to
    flag when Graph genuinely holds a real, never-sent draft.
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        status_code: int | None = None,
        orphaned_provider_draft_id: str | None = None,
    ):
        super().__init__(message)
        self.operation = operation
        self.status_code = status_code
        self.orphaned_provider_draft_id = orphaned_provider_draft_id


class OutboundDispatcher:
    """
    The seam every real send path (Reply, the Reply-All-flavored Reply,
    Forward-via-Compose, Draft-Send) already calls after building an
    OutboundEnvelope and persisting the interaction. Delegates to
    get_mail_provider_client() — the same factory that already returns
    a real GraphMailProviderClient once Graph credentials are
    configured, MockMailProviderClient otherwise — so this class needs
    no provider-specific knowledge of its own.

    Every caller already stores `payload.dispatch_status = "PENDING_SEND"`
    before calling dispatch(); callers are responsible for updating
    that to "SENT" (using this method's returned provider_message_id)
    on success, or "FAILED" on an OutboundDispatchError, since only the
    caller has the Interaction row and DB session in scope.
    """

    async def dispatch(
        self, interaction_id: UUID, envelope: OutboundEnvelope
    ) -> MailProviderSendResult:
        # Best-effort: only needed if this envelope actually carries a
        # large (over the inline-embed threshold) attachment (see
        # graph_client.py's _add_large_attachment) — every other send
        # never touches it. An environment with no storage backend
        # configured (StorageConfigurationError) can still send every
        # attachment-free or small-attachment-only email exactly as
        # before; only a genuinely large attachment would then fail,
        # with a clear error, at _add_large_attachment.
        try:
            storage_service = get_storage_service()
        except StorageConfigurationError:
            storage_service = None

        # mailbox_address=envelope.from_email targets the mailbox this
        # message actually arrived at (for a reply) or was resolved to
        # send from (for compose) — previously ignored, so every send
        # went out via the one globally-configured shared mailbox
        # regardless of what the envelope said. See client_repository.
        # list_active_inbox_emails / graph_mail_poller.py for how a
        # client-specific mailbox gets discovered in the first place.
        mail_provider_client = get_mail_provider_client(
            mailbox_address=envelope.from_email,
            storage_service=storage_service,
        )

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
            raise OutboundDispatchError(
                str(exc),
                operation=getattr(exc, "operation", None),
                status_code=getattr(exc, "status_code", None),
                orphaned_provider_draft_id=getattr(exc, "orphaned_draft_id", None),
            ) from exc

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

# read_receipt_service.py
#
# Outlook-style read-receipt (MDN) handling: which recipients to track
# for an outbound send, and processing an inbound receipt (match it to
# the exact outbound message AND recipient, then record it).
#
# Hard guarantees (see EmailService.receive_email, the one call site):
# - a receipt NEVER creates an Interaction, ticket, SLA event, rule run
#   or notification, whatever happens here;
# - ReadReceiptService.process_receipt NEVER raises — every failure
#   becomes a ReceiptOutcome and a PHI-free log line, so a malformed or
#   hostile receipt can never break normal ingestion or trigger the
#   poller's retry/dead-letter logic;
# - the DB work runs inside a SAVEPOINT, so a failure inside it rolls
#   back only the receipt's own writes, never the surrounding session;
# - only recipient, disposition and timestamps are stored — never the
#   receipt body, quoted content or the original subject.
#
# Matching is exact and nothing else (verified live in Phase 0): the
# receipt's `Original-Message-ID` must equal the stored real Graph
# `internetMessageId` of an OUTBOUND interaction, and its
# `Final-Recipient` must be one of that message's tracked To/Cc
# recipients. Never conversationId (thread-level; five messages shared
# one), subject (localized), timestamps, In-Reply-To/References (absent
# on the observed receipt) or the local placeholder Interaction.message_id.

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ticketing.models.email_read_receipt import RECEIPT_STATUS_CONFIRMED
from app.ticketing.repositories.email_read_receipt_repository import (
    EmailReadReceiptRepository,
)
from app.ticketing.schemas.email import EmailRequest
from app.ticketing.schemas.interaction import ReadReceiptStatusResponse
from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services.mdn_detection import ParsedMdn, parse_mdn

logger = logging.getLogger(__name__)

# Bounded (never unbounded) re-lookups for a receipt whose original is
# not found yet — covers a receipt arriving before the send's own
# transaction (internet_message_id + receipt rows) has committed. Total
# worst-case extra wait: sum of these delays, only for unmatched
# receipts.
UNMATCHED_RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 2.0)


class ReceiptOutcome(str, Enum):
    CONFIRMED = "confirmed"
    DUPLICATE = "duplicate"
    NOT_DISPLAYED = "not_displayed"
    UNMATCHED_NO_ORIGINAL_ID = "unmatched_no_original_id"
    UNMATCHED_UNKNOWN_MESSAGE = "unmatched_unknown_message"
    UNMATCHED_RECIPIENT = "unmatched_recipient"
    MALFORMED = "malformed"
    ERROR = "error"


def receipt_was_requested(interaction: Any) -> bool:
    """
    True only for an OUTBOUND interaction whose persisted envelope asked
    for a read receipt. Lets a read path decide, from data it already
    holds, whether to look receipts up at all — so threads that never
    requested one (every thread while the feature is off) incur no extra
    database round trips.
    """

    payload = getattr(interaction, "payload", None)
    if not isinstance(payload, dict):
        return False
    envelope = payload.get("envelope")
    return isinstance(envelope, dict) and envelope.get("read_receipt_requested") is True


async def load_receipt_statuses(
    db: AsyncSession, interaction_ids: list[Any]
) -> dict[Any, list[ReadReceiptStatusResponse]]:
    """
    Batched, read-only lookup used to annotate thread/open-email
    responses. Savepoint-guarded and exception-swallowing: a failure
    here (e.g. the table not migrated yet) degrades to "no receipt
    info" instead of breaking the thread view or poisoning the
    request's transaction.
    """

    if not interaction_ids:
        return {}

    try:
        async with db.begin_nested():
            grouped = await EmailReadReceiptRepository(db).list_for_interactions(
                list(interaction_ids)
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "read receipt status lookup failed (responses sent without it): error=%s",
            type(exc).__name__,
        )
        return {}

    return {
        interaction_id: [
            ReadReceiptStatusResponse(
                recipient_email=row.recipient_email,
                status=row.status,
                read_at=row.read_at,
            )
            for row in rows
        ]
        for interaction_id, rows in grouped.items()
    }


def tracked_receipt_recipients(envelope: OutboundEnvelope) -> list[str]:
    """
    The recipients a receipt is tracked for: every To and Cc address,
    lower-cased and de-duplicated, order preserved. Bcc is NEVER
    tracked — a Bcc recipient's receipt would expose the Bcc address
    in `Final-Recipient`, and the sender never sees Bcc in the thread.
    """

    ordered: list[str] = []
    seen: set[str] = set()
    for address in [*(envelope.to_emails or [envelope.to_email]), *envelope.cc]:
        normalized = str(address).strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


class ReadReceiptService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        mime_fetcher: Callable[[EmailRequest], Awaitable[bytes | None]] | None = None,
        retry_delays: tuple[float, ...] = UNMATCHED_RETRY_DELAYS_SECONDS,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ):
        self.db = db
        self.repository = EmailReadReceiptRepository(db)
        self._mime_fetcher = mime_fetcher or self._fetch_mime_from_provider
        self._retry_delays = retry_delays
        self._sleep = sleep

    # ------------------------------------------------------------
    # Public entry point — never raises.
    # ------------------------------------------------------------

    async def process_receipt(self, email: EmailRequest) -> ReceiptOutcome:
        try:
            outcome = await self._process(email)
        except Exception as exc:  # noqa: BLE001 — isolation boundary
            # Class name only: exception text can embed addresses/ids.
            logger.warning(
                "read receipt processing failed (consumed, nothing created): "
                "error=%s provider_message_id=%s",
                type(exc).__name__,
                email.provider_message_id,
            )
            return ReceiptOutcome.ERROR

        logger.info(
            "read receipt processed: outcome=%s provider_message_id=%s",
            outcome.value,
            email.provider_message_id,
        )
        return outcome

    # ------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------

    async def _fetch_mime_from_provider(self, email: EmailRequest) -> bytes | None:
        if not email.provider_message_id:
            return None

        # Lazy import: mail_provider imports graph_client at call time
        # (circular otherwise), same convention as its own factory.
        from app.ticketing.services.mail_provider import get_mail_provider_client

        provider = get_mail_provider_client(
            mailbox_address=(email.landed_mailbox or None)
        )
        return await provider.fetch_message_mime(email.provider_message_id)

    async def _process(self, email: EmailRequest) -> ReceiptOutcome:
        mime = await self._mime_fetcher(email)
        parsed = parse_mdn(mime)
        if parsed is None:
            return ReceiptOutcome.MALFORMED
        if not parsed.original_message_id:
            return ReceiptOutcome.UNMATCHED_NO_ORIGINAL_ID
        if not parsed.final_recipient:
            return ReceiptOutcome.UNMATCHED_RECIPIENT

        interaction = await self._find_original(parsed.original_message_id)
        if interaction is None:
            return ReceiptOutcome.UNMATCHED_UNKNOWN_MESSAGE

        # Everything below writes; keep it in a savepoint so a failure
        # (e.g. a concurrent duplicate hitting a unique index) rolls
        # back only this receipt's own writes.
        async with self.db.begin_nested():
            return await self._record(email, parsed, interaction.interaction_id)

    async def _find_original(self, original_message_id: str):
        interaction = await self.repository.find_outbound_by_internet_message_id(
            original_message_id
        )
        for delay in self._retry_delays:
            if interaction is not None:
                break
            await self._sleep(delay)
            interaction = await self.repository.find_outbound_by_internet_message_id(
                original_message_id
            )
        return interaction

    async def _record(
        self, email: EmailRequest, parsed: ParsedMdn, interaction_id
    ) -> ReceiptOutcome:
        row = await self.repository.get_for_update(
            interaction_id, parsed.final_recipient
        )
        if row is None:
            # Not a tracked To/Cc recipient: wrong person, a forward, a
            # Bcc, or an alias. Never attributed to anyone else.
            return ReceiptOutcome.UNMATCHED_RECIPIENT

        if parsed.mdn_message_id and await self.repository.mdn_already_recorded(
            parsed.mdn_message_id
        ):
            return ReceiptOutcome.DUPLICATE

        read_at = parsed.receipt_date or email.received_at

        if row.status == RECEIPT_STATUS_CONFIRMED:
            # Already confirmed: never regress, never duplicate; only
            # ever move the recorded time earlier.
            await self.repository.keep_earliest_read_at(row, read_at)
            return ReceiptOutcome.DUPLICATE

        if not parsed.is_displayed:
            # A receipt whose Disposition is not (or does not say)
            # `displayed` is never marked CONFIRMED. Preserve the raw
            # disposition so a future mapping can be added without
            # losing it; the row stays REQUESTED.
            row.disposition = parsed.disposition
            row.mdn_message_id = parsed.mdn_message_id
            row.received_at = email.received_at
            await self.db.flush()
            return ReceiptOutcome.NOT_DISPLAYED

        await self.repository.confirm(
            row,
            read_at=read_at,
            disposition=parsed.disposition,
            mdn_message_id=parsed.mdn_message_id,
            received_at=email.received_at,
        )
        return ReceiptOutcome.CONFIRMED

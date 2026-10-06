# mdn_detection.py
#
# Pure, I/O-free detection and parsing of an inbound Outlook-style read
# receipt (RFC 8098 Message Disposition Notification, "MDN"). Kept
# deliberately separate from normal email parsing (mail_mapping_service)
# and from bounce detection (bounce_detection): a read receipt must be
# recognised BEFORE both so it can never become a ghost client email, a
# ticket, an SLA event or a bounce.
#
# Verified live (read-receipt Phase 0): an Outlook receipt arrives with
# Graph item class REPORT.IPM.Note.IPNRN; the Graph JSON
# `internetMessageHeaders` Content-Type is MISLEADING
# (`application/ms-tnef`) while the real MIME (`GET /messages/{id}/$value`)
# is `multipart/report; report-type=disposition-notification` carrying a
# `message/disposition-notification` part with Original-Message-ID,
# Final-Recipient and Disposition. The receipt has no In-Reply-To /
# References and shares only a thread-level conversationId, so none of
# those (nor the subject, nor the receipt's own Message-ID) are ever
# used for matching.

import logging
from dataclasses import dataclass
from datetime import datetime
from email import message_from_bytes, policy
from email.message import Message
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

# Observed live: REPORT.IPM.Note.IPNRN (read). The sibling classes
# (e.g. IPNNRN, "not read") share this prefix; their exact semantics
# have NOT been observed, so they are detected as receipts (consumed,
# never turned into tickets) but are never marked CONFIRMED unless the
# parsed Disposition says `displayed`.
MDN_ITEM_CLASS_PREFIX = "REPORT.IPM.Note.IPN"

# A receipt is tiny; refuse to parse anything absurdly large.
MAX_MDN_MIME_BYTES = 2 * 1024 * 1024

_MDN_REPORT_TYPE = "report-type=disposition-notification"


@dataclass(frozen=True)
class ParsedMdn:
    """
    Only the fields UTMS needs — never the body, quoted content or the
    original subject. Any field may be None for a malformed receipt.
    """

    original_message_id: str | None
    final_recipient: str | None  # normalized, lower-case, no `RFC822;` prefix
    disposition: str | None  # raw field, whitespace-normalized
    disposition_type: str | None  # e.g. "displayed" (lower-case)
    receipt_date: datetime | None  # the receipt's own Date header
    mdn_message_id: str | None  # the receipt message's own Message-ID

    @property
    def is_displayed(self) -> bool:
        """True only when the Disposition explicitly says `displayed`."""

        return self.disposition_type == "displayed"


def is_read_receipt_candidate(
    item_class: str | None, content_type_header: str | None = None
) -> bool:
    """
    Cheap pre-check (no MIME fetch). True when:

    1. the Graph/MAPI item class starts with REPORT.IPM.Note.IPN
       (primary — language-independent), or
    2. the Graph-reported Content-Type header explicitly says
       `report-type=disposition-notification` (secondary, for a
       standards-based sender; never relied on alone for Outlook
       because Graph reports `application/ms-tnef` for those).

    A subject such as "Read:" is deliberately NOT a signal (localized).
    """

    if isinstance(item_class, str) and item_class.strip().upper().startswith(
        MDN_ITEM_CLASS_PREFIX.upper()
    ):
        return True

    if content_type_header and _MDN_REPORT_TYPE in "".join(
        content_type_header.lower().split()
    ):
        return True

    return False


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _normalize_original_message_id(value: str | None) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    # Keep the angle-bracketed form Graph reports for internetMessageId.
    # Some systems omit the brackets; add them so the exact comparison
    # against the stored internetMessageId is format-independent.
    if not (text.startswith("<") and text.endswith(">")):
        text = "<" + text.strip("<>") + ">"
    return text


def _normalize_final_recipient(value: str | None) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    # `RFC822; user@example.com` -> `user@example.com`
    address = text.split(";", 1)[1].strip() if ";" in text else text
    address = address.strip("<> ").lower()
    return address if "@" in address else None


def _disposition_type(disposition: str | None) -> str | None:
    # Disposition: <action-mode>/<sending-mode>; <type>[/<modifier>]
    if not disposition or ";" not in disposition:
        return None
    type_part = disposition.rsplit(";", 1)[1].strip().lower()
    return type_part.split("/", 1)[0].strip() or None


def _dsn_fields(part: Message) -> Message | None:
    payload = part.get_payload()
    if isinstance(payload, list) and payload:
        first = payload[0]
        return first if isinstance(first, Message) else None
    if isinstance(payload, str):
        from email import message_from_string

        return message_from_string(payload, policy=policy.default)
    return None


def parse_mdn(mime_bytes: bytes | None) -> ParsedMdn | None:
    """
    Parses a receipt's full MIME. Returns None only when the bytes are
    unusable (empty, oversized or unparseable); a parseable message that
    simply lacks the machine-readable part yields a ParsedMdn whose
    fields are None. Never raises.
    """

    if not mime_bytes or len(mime_bytes) > MAX_MDN_MIME_BYTES:
        return None

    try:
        message = message_from_bytes(mime_bytes, policy=policy.default)

        original_message_id = final_recipient = disposition = None
        for part in message.walk():
            if part.get_content_type() != "message/disposition-notification":
                continue
            fields = _dsn_fields(part)
            if fields is None:
                continue
            original_message_id = fields.get("Original-Message-ID")
            final_recipient = fields.get("Final-Recipient")
            disposition = fields.get("Disposition")
            break

        receipt_date = None
        raw_date = message.get("Date")
        if raw_date:
            try:
                receipt_date = parsedate_to_datetime(str(raw_date))
            except (TypeError, ValueError):
                receipt_date = None

        disposition_text = _clean(disposition)
        return ParsedMdn(
            original_message_id=_normalize_original_message_id(
                _clean(original_message_id)
            ),
            final_recipient=_normalize_final_recipient(_clean(final_recipient)),
            disposition=disposition_text,
            disposition_type=_disposition_type(disposition_text),
            receipt_date=receipt_date,
            mdn_message_id=_clean(message.get("Message-ID")),
        )
    except Exception:  # noqa: BLE001 — a hostile/odd MIME must never raise
        logger.warning("MDN parse failed (unparseable MIME)", exc_info=True)
        return None

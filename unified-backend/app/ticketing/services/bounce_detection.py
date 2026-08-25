# bounce_detection.py
#
# Phase 2 hardening: a non-delivery report (NDR)/bounce message must
# never be treated as a real client email — before this module
# existed, EmailService.receive_email had zero special-casing for
# one, so a bounce landing in the shared mailbox became an ordinary
# ticket + MAIL_RECEIVED notification like any other inbound mail.
#
# Pure string-matching, deliberately with no I/O and no dependency on
# any Graph-specific payload shape, so it's independently testable and
# reusable regardless of what's available at a given call site
# (mail_mapping_service.py is the only current caller).

import logging

logger = logging.getLogger(__name__)

_BOUNCE_SENDER_LOCAL_PARTS = {"postmaster", "mailer-daemon", "mailerdaemon"}

_BOUNCE_SUBJECT_PREFIXES = (
    "undeliverable:",
    "delivery status notification",
    "mail delivery failed",
    "returned mail",
    "undelivered mail returned to sender",
    "failure notice",
)

_BOUNCE_CONTENT_TYPE_MARKERS = (
    "report-type=delivery-status",
    "multipart/report",
    "message/delivery-status",
)


def _sender_is_bounce_address(from_email: str | None) -> bool:
    if not from_email or "@" not in from_email:
        return False
    local_part = from_email.split("@", 1)[0].strip().lower()
    return local_part in _BOUNCE_SENDER_LOCAL_PARTS


def _subject_is_bounce_shaped(subject: str | None) -> bool:
    if not subject:
        return False
    normalized = subject.strip().lower()
    return normalized.startswith(_BOUNCE_SUBJECT_PREFIXES)


def _content_type_is_bounce_shaped(content_type_header: str | None) -> bool:
    if not content_type_header:
        return False
    normalized = content_type_header.lower()
    return any(marker in normalized for marker in _BOUNCE_CONTENT_TYPE_MARKERS)


def is_bounce_notification(
    from_email: str | None,
    subject: str | None,
    content_type_header: str | None = None,
) -> bool:
    """
    True if this inbound message is a non-delivery report (NDR)/bounce
    rather than a real client email. Any one signal is sufficient:

    - sender local-part is postmaster/mailer-daemon (the two addresses
      every real mail transport agent uses to originate a bounce —
      never used by a genuine client sender).
    - subject starts with a standard bounce-report prefix (Exchange/
      Outlook, Gmail, and Postfix/sendmail all use one of these).
    - the raw Content-Type header (when available) indicates a
      multipart/report delivery-status body per RFC 3462/3464 — best-
      effort/optional, since not every transport reliably surfaces raw
      headers.

    False positives are the real risk here (misclassifying a genuine
    client email skips ticket creation/rules/SLA for it entirely), so
    each signal is deliberately a strict prefix/exact-local-part match,
    never a loose substring search over the whole subject/body.
    """

    return (
        _sender_is_bounce_address(from_email)
        or _subject_is_bounce_shaped(subject)
        or _content_type_is_bounce_shaped(content_type_header)
    )

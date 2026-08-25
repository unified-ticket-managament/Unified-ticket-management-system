# recipient_validation.py
#
# Shared To/Cc/Bcc recipient validation for every outbound-mail-
# composing endpoint (Compose, Forward, and both Reply variants —
# ticket-scoped and pre-ticket). Two layers:
#
# 1. Syntax — via email_validator.validate_email (already a
#    transitive pydantic[email] dependency, the exact same library
#    backing pydantic's own EmailStr fields). Compose/Forward accept
#    recipients as multipart Form fields and construct
#    ComposeEmailRequest/ForwardToInternalUserRequest manually inside
#    the route function, *after* FastAPI's own body-parsing has
#    already happened — an invalid address there raised a raw
#    pydantic.ValidationError with no handler registered for it (see
#    app/main.py's exception handlers), surfacing as an unhandled 500
#    rather than a clean 400. Calling this first avoids ever reaching
#    that construction with a bad address.
# 2. Domain deliverability (check_deliverability=True) — confirms the
#    domain has real MX (or fallback A/AAAA) records, i.e. it can
#    plausibly receive mail. This is NOT proof any specific mailbox on
#    that domain exists — no SMTP-level probe is performed or should
#    ever be trusted for that; it only rules out a domain that could
#    never receive mail at all (typo'd TLD, nonexistent domain, a
#    domain with no mail exchanger configured).

import asyncio

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException, status

# Phase 3 hardening: the email-validator library's own default
# deliverability-check timeout is 15 seconds *per address*
# (email_validator.DEFAULT_TIMEOUT), and validation used to run one
# address at a time in a single worker thread — so a slow-to-resolve
# domain, or several Cc/Bcc recipients, could leave a Send button
# showing no feedback for many seconds (up to 15s x N) before the
# correct rejection finally surfaced, easily reading as "nothing
# happened" even though the check was working correctly. Lowering the
# timeout and validating addresses concurrently (see
# ensure_recipients_are_valid below) bounds worst-case latency to one
# timeout window regardless of recipient count. This does NOT change
# whether a domain is accepted or rejected — check_deliverability=True
# and the exception handling below are unchanged; a genuine DNS
# timeout still falls through to the library's own existing "unknown
# deliverability is passable" behavior, it just gives up sooner.
DELIVERABILITY_CHECK_TIMEOUT_SECONDS = 5


def ensure_recipient_address_is_valid(address: str) -> None:
    """
    Raises HTTPException(400) if `address` is not a syntactically
    valid, plausibly-deliverable email address.
    """

    try:
        validate_email(
            address,
            check_deliverability=True,
            timeout=DELIVERABILITY_CHECK_TIMEOUT_SECONDS,
        )
    except EmailNotValidError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Enter a valid email address or check the domain: {address}",
        )
    except Exception:
        # Belt-and-suspenders: email_validator's own deliverability
        # check already wraps any unexpected DNS/resolver error into
        # EmailUndeliverableError (a subclass of EmailNotValidError,
        # caught above) before it ever reaches this function — so this
        # branch isn't known to be reachable today. It exists purely
        # as insurance against a future library-version change ever
        # letting an unanticipated exception escape as an unhandled
        # 500 instead of the same clean, expected 400.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Enter a valid email address or check the domain: {address}",
        )


async def ensure_recipients_are_valid(
    *,
    to: str | list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> None:
    """
    Validates every address across To/Cc/Bcc in one call — the send
    must be rejected if any single one is invalid, not just the first
    field checked. `to` accepts either a single address (Compose/
    Forward/Reply's own single "To" override) or a list, and `None`/
    empty values are silently skipped (an omitted Cc/Bcc, or a Reply
    that didn't override its default recipient, is never itself an
    error).

    Every address is validated concurrently, each in its own worker
    thread via asyncio.to_thread — check_deliverability=True means
    each one does a real, synchronous MX/A/AAAA lookup (see this
    module's own docstring), which would otherwise block the event
    loop for the duration of that lookup; running them concurrently
    (rather than one after another) also bounds the worst-case total
    latency to a single DELIVERABILITY_CHECK_TIMEOUT_SECONDS window
    regardless of how many recipients are being validated. An
    HTTPException raised inside a thread propagates back out unchanged
    (same status code, same message) — asyncio.gather re-raises the
    first worker's exception as-is once all threads have settled.
    """

    addresses: list[str] = []
    if isinstance(to, str):
        if to:
            addresses.append(to)
    elif to:
        addresses.extend(to)
    addresses.extend(cc or [])
    addresses.extend(bcc or [])

    if not addresses:
        return

    await asyncio.gather(
        *(asyncio.to_thread(ensure_recipient_address_is_valid, address) for address in addresses)
    )

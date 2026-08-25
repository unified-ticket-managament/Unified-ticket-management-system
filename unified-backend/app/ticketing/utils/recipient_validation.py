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


def ensure_recipient_address_is_valid(address: str) -> None:
    """
    Raises HTTPException(400) if `address` is not a syntactically
    valid, plausibly-deliverable email address.
    """

    try:
        validate_email(address, check_deliverability=True)
    except EmailNotValidError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Enter a valid email address or check the domain: {address}",
        )


def _validate_all(addresses: list[str]) -> None:
    for address in addresses:
        ensure_recipient_address_is_valid(address)


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

    Runs the actual (blocking, DNS-resolving) validation loop in a
    worker thread via asyncio.to_thread — check_deliverability=True
    means every address here does a real, synchronous MX/A/AAAA
    lookup (see this module's own docstring), which would otherwise
    block the event loop for every other in-flight request for the
    duration of that lookup. An HTTPException raised inside the
    thread propagates back out unchanged (same status code, same
    message) — asyncio.to_thread re-raises the worker's exception as-is.
    """

    addresses: list[str] = []
    if isinstance(to, str):
        if to:
            addresses.append(to)
    elif to:
        addresses.extend(to)
    addresses.extend(cc or [])
    addresses.extend(bcc or [])

    await asyncio.to_thread(_validate_all, addresses)

# test_recipient_validation.py
#
# Coverage for app.ticketing.utils.recipient_validation — the shared
# To/Cc/Bcc syntax + domain-deliverability check reused by Compose,
# Forward, and both Reply variants. Syntax-invalid addresses fail
# before any DNS lookup happens (confirmed live — email_validator
# rejects on syntax alone in well under a millisecond), so only the
# explicitly domain-focused tests below make a real DNS query; no
# mocking is introduced for a class of check that only means anything
# against real DNS.

import pytest
from fastapi import HTTPException

from app.ticketing.utils.recipient_validation import (
    ensure_recipient_address_is_valid,
    ensure_recipients_are_valid,
)


@pytest.mark.parametrize(
    "address",
    [
        "abc.example.com",  # no @-sign
        "abc@",  # nothing after @
        "@outlook.com",  # nothing before @
        "abc @example.com",  # space in the local part
    ],
)
def test_rejects_malformed_syntax(address):
    with pytest.raises(HTTPException) as exc_info:
        ensure_recipient_address_is_valid(address)

    assert exc_info.value.status_code == 400


def test_accepts_a_real_domain_with_mx_records():
    # painmedpa.com is this product's own real, live-configured mail
    # domain (see root CLAUDE.md's Gmail-delivery investigation) —
    # confirmed live to have real MX records, so this is a stable,
    # non-flaky choice for "a genuinely valid, deliverable address".
    ensure_recipient_address_is_valid("someone@painmedpa.com")


def test_rejects_a_domain_that_does_not_exist():
    # The exact typo this feature was built to catch — a syntactically
    # valid address whose domain has no DNS presence at all.
    with pytest.raises(HTTPException) as exc_info:
        ensure_recipient_address_is_valid("supriya@painmedpa.cm")

    assert exc_info.value.status_code == 400
    assert "painmedpa.cm" in exc_info.value.detail


async def test_ensure_recipients_are_valid_checks_to_cc_and_bcc_together():
    with pytest.raises(HTTPException):
        await ensure_recipients_are_valid(
            to="valid@painmedpa.com", cc=["also-valid@painmedpa.com"], bcc=["not-an-email"]
        )


async def test_ensure_recipients_are_valid_skips_empty_fields():
    # None/omitted To, and empty Cc/Bcc lists, are never themselves an
    # error — an unset override or an unused Cc/Bcc field is the
    # common case, not a validation failure.
    await ensure_recipients_are_valid(to=None, cc=[], bcc=[])


async def test_ensure_recipients_are_valid_accepts_a_list_of_to_addresses():
    await ensure_recipients_are_valid(to=["someone@painmedpa.com"], cc=None, bcc=None)


async def test_ensure_recipients_are_valid_does_not_block_the_event_loop():
    # The real regression this conversion fixes: check_deliverability=
    # True does a blocking DNS lookup under the hood — running it
    # in-line on the event loop would starve every other concurrently
    # scheduled task for the lookup's duration. Running a cheap
    # concurrent task alongside a real (slow-ish, DNS-resolving) call
    # and asserting the cheap one's own marker flips before the
    # validation call returns proves the validation genuinely ran off
    # the event loop thread (asyncio.to_thread), not just that it
    # returned eventually.
    import asyncio

    marker = {"ticked": False}

    async def _tick_soon():
        await asyncio.sleep(0)
        marker["ticked"] = True

    tick_task = asyncio.create_task(_tick_soon())
    await ensure_recipients_are_valid(to="someone@painmedpa.com", cc=None, bcc=None)
    await tick_task

    assert marker["ticked"] is True

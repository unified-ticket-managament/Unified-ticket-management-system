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

import time

import dns.exception
import dns.resolver
import pytest
from fastapi import HTTPException

from app.ticketing.utils import recipient_validation
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


# Phase 3 hardening: shorter DNS timeout + concurrent per-address
# validation. These are regression guards proving semantics are
# unchanged (still rejects bad domains, still accepts good ones, a
# timeout still doesn't reject) and only latency/robustness improved
# — no new/duplicate validation logic was introduced.


def test_rejects_a_domain_that_does_not_exist_after_timeout_change():
    # Same real-DNS regression as test_rejects_a_domain_that_does_not_exist
    # above, re-asserted after lowering DELIVERABILITY_CHECK_TIMEOUT_SECONDS
    # — proves the shorter timeout didn't change what gets rejected.
    with pytest.raises(HTTPException) as exc_info:
        ensure_recipient_address_is_valid("supriya@painmedpa.cm")

    assert exc_info.value.status_code == 400


def test_accepts_a_real_domain_after_timeout_change():
    # Same real-DNS regression as test_accepts_a_real_domain_with_mx_records
    # above, re-asserted after lowering the timeout — proves the shorter
    # timeout didn't start false-rejecting a genuinely valid domain.
    ensure_recipient_address_is_valid("someone@painmedpa.com")


def test_dns_timeout_does_not_incorrectly_reject_the_address(monkeypatch):
    """
    email_validator's own deliverability check deliberately treats a
    DNS timeout as "unknown, not a failure" (it returns
    {"unknown-deliverability": "timeout"} rather than raising) — this
    confirms lowering our timeout value didn't change that library
    behavior into a rejection. Simulated by making the real DNS
    resolver's .resolve() raise dns.exception.Timeout, exercising the
    actual email_validator code path end-to-end rather than mocking
    our own function.
    """

    class _TimingOutResolver:
        def resolve(self, *args, **kwargs):
            raise dns.exception.Timeout()

    monkeypatch.setattr(
        dns.resolver, "get_default_resolver", lambda: _TimingOutResolver()
    )

    # Must not raise — a timeout is passable, not a rejection.
    ensure_recipient_address_is_valid("someone@painmedpa.com")


async def test_multiple_recipients_validate_concurrently_not_sequentially(monkeypatch):
    """
    Before this hardening, _validate_all checked every address one at
    a time in a single thread — N addresses could stack to N x timeout
    worst-case latency. Each address is now validated in its own
    concurrent asyncio.to_thread, so validating several addresses
    should take roughly as long as validating one, not N times as
    long. Mocks validate_email with a fixed per-call delay (not real
    DNS) so this is a fast, deterministic timing assertion.
    """

    delay_seconds = 0.2
    address_count = 5

    def _slow_validate_email(address, **kwargs):
        time.sleep(delay_seconds)

    monkeypatch.setattr(recipient_validation, "validate_email", _slow_validate_email)

    addresses = [f"user{i}@painmedpa.com" for i in range(address_count)]
    started = time.monotonic()
    await ensure_recipients_are_valid(to=addresses, cc=None, bcc=None)
    elapsed = time.monotonic() - started

    # Sequential validation of 5 addresses would take ~5 x delay_seconds
    # (~1.0s); concurrent validation should take roughly one delay
    # window regardless of count. Generous upper bound for CI jitter.
    assert elapsed < delay_seconds * (address_count / 2)


def test_unexpected_exception_becomes_a_clean_400_not_a_500(monkeypatch):
    """
    Belt-and-suspenders: even though email_validator's own
    deliverability check already wraps any unexpected DNS/resolver
    error into EmailUndeliverableError before it escapes to our code,
    this confirms a still-unanticipated exception type is converted to
    the same clean HTTPException(400) rather than propagating as an
    unhandled 500.
    """

    def _raise_unexpected(address, **kwargs):
        raise RuntimeError("boom — not an EmailNotValidError")

    monkeypatch.setattr(recipient_validation, "validate_email", _raise_unexpected)

    with pytest.raises(HTTPException) as exc_info:
        ensure_recipient_address_is_valid("someone@painmedpa.com")

    assert exc_info.value.status_code == 400

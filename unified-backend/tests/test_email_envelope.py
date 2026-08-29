# test_email_envelope.py
#
# Pure-logic coverage for build_reply_envelope/build_compose_envelope
# (email_envelope.py) — no DB. Covers the fix for a real bug found
# live this session: a reply to a thread with no resolvable Client
# (the Graph-mailbox Site Lead fallback, see
# email_service.is_configured_graph_mailbox()) used to never build an
# envelope at all — silently stuck at dispatch_status="NO_RECIPIENT"
# with nothing ever sent — because build_reply_envelope used to
# require a Client object just to read its inbox_email. It now takes
# a plain from_email string instead, so callers can supply the
# inbound message's own arrival address when there's no Client.

from app.ticketing.enums import InteractionDirection
from app.ticketing.schemas.payloads import EmailPayload
from app.ticketing.services.email_envelope import (
    build_agent_signature,
    build_agent_signature_html,
    build_compose_envelope,
    build_reply_envelope,
    resolve_reply_addresses,
)


def _inbound_payload(**overrides) -> EmailPayload:
    base = dict(
        subject="Question about my visit",
        body="Hi, I had a question.",
        from_email="patient@example.com",
        to_email="ticketing@probeps.com",
    )
    base.update(overrides)
    return EmailPayload(**base)


def test_build_reply_envelope_uses_client_inbox_email_when_given():
    envelope = build_reply_envelope(
        from_email="clientinbox@example.com",
        inbound_payload=_inbound_payload(),
        inbound_message_id="<original@example.com>",
        body="Reply body.",
    )

    assert envelope is not None
    assert envelope.from_email == "clientinbox@example.com"
    assert envelope.to_email == "patient@example.com"


def test_build_reply_envelope_falls_back_to_inbound_to_email_when_no_client():
    """
    The exact fix for the live bug: a client-less thread's reply-From
    address is the inbound message's own arrival address
    (EmailPayload.to_email) — previously callers simply never invoked
    this function at all in that case, leaving dispatch_status stuck
    at NO_RECIPIENT with the email silently never sent.
    """

    payload = _inbound_payload(to_email="ticketing@probeps.com")

    envelope = build_reply_envelope(
        from_email=payload.to_email,
        inbound_payload=payload,
        inbound_message_id="<original@example.com>",
        body="Reply body.",
    )

    assert envelope is not None
    assert envelope.from_email == "ticketing@probeps.com"
    assert envelope.to_email == "patient@example.com"


# ---------------------------------------------------------------
# resolve_reply_addresses / build_reply_envelope's default_to_email —
# the fix for a real, previously-shipped bug: replying to a
# Compose-authored (OUTBOUND) thread root inverted From/To, because
# EmailPayload's from_email/to_email are populated the OPPOSITE way
# round for an OUTBOUND root (see compose_email) vs. the INBOUND case
# every caller used to assume unconditionally.
# ---------------------------------------------------------------


def _outbound_payload(**overrides) -> EmailPayload:
    # Mirrors compose_email's own EmailPayload construction: from_email
    # is this platform's own sending mailbox, to_email is the external
    # recipient — the opposite pairing from _inbound_payload above.
    base = dict(
        subject="Following up on your account",
        body="Hi, following up.",
        from_email="ticketing@probeps.com",
        to_email="gogineni@painmedpa.com",
    )
    base.update(overrides)
    return EmailPayload(**base)


def test_resolve_reply_addresses_inbound_root():
    payload = _inbound_payload()

    from_email, default_to_email = resolve_reply_addresses(
        payload, InteractionDirection.INBOUND
    )

    assert from_email == payload.to_email
    assert default_to_email == payload.from_email


def test_resolve_reply_addresses_outbound_root():
    payload = _outbound_payload()

    from_email, default_to_email = resolve_reply_addresses(
        payload, InteractionDirection.OUTBOUND
    )

    assert from_email == "ticketing@probeps.com"
    assert default_to_email == "gogineni@painmedpa.com"


def test_build_reply_envelope_on_outbound_root_sends_from_platform_to_client():
    """
    The exact bug from the live report: replying to a Sent-Items
    (Compose-authored) email must dispatch FROM this platform's own
    mailbox TO the external client — not the inverse a direction-blind
    caller used to produce.
    """

    payload = _outbound_payload()
    from_email, default_to_email = resolve_reply_addresses(
        payload, InteractionDirection.OUTBOUND
    )

    envelope = build_reply_envelope(
        from_email=from_email,
        inbound_payload=payload,
        inbound_message_id=None,
        body="Following up on my last email.",
        default_to_email=default_to_email,
    )

    assert envelope is not None
    assert envelope.from_email == "ticketing@probeps.com"
    assert envelope.to_email == "gogineni@painmedpa.com"


def test_build_reply_envelope_default_to_email_omitted_keeps_old_behavior():
    """
    Backward compatibility: a caller that doesn't pass default_to_email
    (every pre-existing call site/test) must still fall back to
    inbound_payload.from_email exactly as before this parameter
    existed.
    """

    envelope = build_reply_envelope(
        from_email="ticketing@probeps.com",
        inbound_payload=_inbound_payload(),
        inbound_message_id="<original@example.com>",
        body="Reply body.",
    )

    assert envelope is not None
    assert envelope.to_email == "patient@example.com"


def test_build_reply_envelope_none_when_no_recipient_resolvable():
    payload = _inbound_payload(from_email=None)

    envelope = build_reply_envelope(
        from_email="ticketing@probeps.com",
        inbound_payload=payload,
        inbound_message_id="<original@example.com>",
        body="Reply body.",
    )

    assert envelope is None


def test_build_reply_envelope_message_id_domain_matches_from_email():
    envelope = build_reply_envelope(
        from_email="ticketing@probeps.com",
        inbound_payload=_inbound_payload(),
        inbound_message_id="<original@example.com>",
        body="Reply body.",
    )

    assert envelope is not None
    assert envelope.message_id.endswith("@probeps.com>")


def test_build_reply_envelope_account_manager_email_none_is_safe():
    envelope = build_reply_envelope(
        from_email="ticketing@probeps.com",
        inbound_payload=_inbound_payload(),
        inbound_message_id="<original@example.com>",
        body="Reply body.",
        account_manager_email=None,
    )

    assert envelope is not None
    assert envelope.cc == []


def test_build_reply_envelope_carries_reply_to_provider_message_id_and_reply_all():
    envelope = build_reply_envelope(
        from_email="ticketing@probeps.com",
        inbound_payload=_inbound_payload(),
        inbound_message_id="<original@example.com>",
        body="Reply body.",
        reply_to_provider_message_id="AAMkAGraphNativeId==",
        reply_all=True,
    )

    assert envelope is not None
    assert envelope.reply_to_provider_message_id == "AAMkAGraphNativeId=="
    assert envelope.reply_all is True


def test_build_reply_envelope_defaults_reply_fields_to_sendmail_behavior():
    envelope = build_reply_envelope(
        from_email="ticketing@probeps.com",
        inbound_payload=_inbound_payload(),
        inbound_message_id="<original@example.com>",
        body="Reply body.",
    )

    assert envelope is not None
    assert envelope.reply_to_provider_message_id is None
    assert envelope.reply_all is False


# ---------------------------------------------------------------
# body_html — Outlook-style clipboard paste. Additive: None (the
# default) must leave every pre-existing envelope shape untouched;
# when given, it's sanitized (via app.ticketing.utils.html_sanitizer)
# before landing on the envelope.
# ---------------------------------------------------------------


def test_build_reply_envelope_body_html_none_when_omitted():
    envelope = build_reply_envelope(
        from_email="ticketing@probeps.com",
        inbound_payload=_inbound_payload(),
        inbound_message_id="<original@example.com>",
        body="Reply body.",
    )

    assert envelope is not None
    assert envelope.body_html is None


def test_build_reply_envelope_carries_sanitized_body_html_when_given():
    envelope = build_reply_envelope(
        from_email="ticketing@probeps.com",
        inbound_payload=_inbound_payload(),
        inbound_message_id="<original@example.com>",
        body="Reply body.",
        body_html="<p>Hello</p><script>alert(1)</script>",
    )

    assert envelope is not None
    assert envelope.body_html == "<p>Hello</p>"


def test_build_compose_envelope_body_html_none_when_omitted():
    envelope = build_compose_envelope(
        from_email="ticketing@probeps.com",
        to_email="patient@example.com",
        subject="Following up",
        body="Hello!",
    )

    assert envelope.body_html is None


def test_build_compose_envelope_carries_sanitized_body_html_when_given():
    envelope = build_compose_envelope(
        from_email="ticketing@probeps.com",
        to_email="patient@example.com",
        subject="Following up",
        body="Hello!",
        body_html='<p onclick="evil()">Hi</p><img src="https://evil.com/x.png">',
    )

    assert envelope.body_html == "<p>Hi</p>"


def test_build_compose_envelope_uses_shared_mailbox_as_from_not_client_address():
    """
    Client.inbox_email now stores the client's own real address (used
    to identify them as a sender on inbound) — Compose must never send
    From that address. The caller resolves the shared mailbox address
    and passes it in directly; build_compose_envelope no longer takes
    a Client object at all.
    """

    envelope = build_compose_envelope(
        from_email="ticketing@probeps.com",
        to_email="patient@example.com",
        subject="Following up",
        body="Hello!",
    )

    assert envelope.from_email == "ticketing@probeps.com"
    assert envelope.to_email == "patient@example.com"
    assert envelope.message_id.endswith("@probeps.com>")

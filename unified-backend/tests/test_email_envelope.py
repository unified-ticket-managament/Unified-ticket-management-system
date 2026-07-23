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

from app.ticketing.schemas.payloads import EmailPayload
from app.ticketing.services.email_envelope import build_compose_envelope, build_reply_envelope


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

# test_reply_subject_edit.py
#
# An agent-edited Reply / Reply All subject must reach the mail provider
# unchanged, while an untouched reply keeps its historical behavior
# (default "Re: <original>", Graph deriving its own subject).

import pytest

from app.ticketing.schemas.payloads import EmailPayload
from app.ticketing.schemas.ticket_action import InteractionReplyRequest, ReplyCreate
from app.ticketing.schemas.ticket_draft import TicketReplyDraftSaveRequest
from app.ticketing.services.email_envelope import build_reply_envelope
from app.ticketing.services.graph_client import _build_reply_action_body
from app.ticketing.services.interaction_service import InteractionService


def _inbound(subject="Claim Status") -> EmailPayload:
    return EmailPayload(
        subject=subject,
        body="Hi",
        from_email="patient@example.com",
        to_email="ticketing@probeps.com",
    )


def _build(subject=None, reply_all=False, **kw):
    return build_reply_envelope(
        from_email="ticketing@probeps.com",
        inbound_payload=_inbound(),
        inbound_message_id="<orig@example.com>",
        body="Reply body.",
        reply_to_provider_message_id="graph-id",
        reply_all=reply_all,
        subject=subject,
        **kw,
    )


@pytest.mark.parametrize("sent", [None, "", "   ", "Re: Claim Status"])
def test_untouched_subject_keeps_default_and_graph_behavior(sent):
    envelope = _build(subject=sent)
    assert envelope.subject == "Re: Claim Status"
    assert envelope.subject_overridden is False
    assert "subject" not in _build_reply_action_body(envelope)["message"]


@pytest.mark.parametrize("reply_all", [False, True])
def test_edited_subject_wins_and_reaches_graph_body(reply_all):
    envelope = _build(subject="Urgent Claim Update", reply_all=reply_all)
    assert envelope.subject == "Urgent Claim Update"
    assert envelope.subject_overridden is True
    assert envelope.reply_all is reply_all
    assert _build_reply_action_body(envelope)["message"]["subject"] == "Urgent Claim Update"


def test_special_characters_and_long_subject_are_preserved():
    special = "Re: [URGENT] Claim #123 - Patient's Account"
    assert _build(subject=special).subject == special
    long_subject = "x" * 500
    assert _build(subject=long_subject).subject == long_subject


def test_editing_subject_does_not_change_recipients():
    base = _build(cc=["a@example.com"], bcc=["b@example.com"])
    edited = _build(subject="Other", cc=["a@example.com"], bcc=["b@example.com"])
    assert (edited.to_email, edited.cc, edited.bcc) == (base.to_email, base.cc, base.bcc)


def test_request_schemas_accept_optional_subject():
    assert ReplyCreate(message="m").subject is None
    assert ReplyCreate(message="m", subject="S").subject == "S"
    assert InteractionReplyRequest(message="m", subject="S").subject == "S"
    with pytest.raises(ValueError):
        ReplyCreate(message="m", subject="x" * 501)


def test_ticket_reply_draft_payload_keeps_edited_subject():
    payload = InteractionService._ticket_reply_draft_payload(
        TicketReplyDraftSaveRequest(message="m", subject="Updated Subject")
    )
    assert payload["subject"] == "Updated Subject"

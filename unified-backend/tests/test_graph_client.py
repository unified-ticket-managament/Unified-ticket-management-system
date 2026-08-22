# test_graph_client.py
#
# Pure-logic coverage for the Graph message-building helpers in
# app.ticketing.services.graph_client — _build_send_mail_message,
# _build_reply_action_body, _build_graph_attachments. No DB, no
# network, no httpx call — these are plain dict-builder functions.
#
# The single most important guarantee tested here: every one of these
# functions must produce a BYTE-IDENTICAL result to before body_html/
# is_inline/content_id existed, whenever those fields are absent —
# this is the shared code path behind every existing plain-text mail
# send in the app, so a regression here would affect every one of
# them, not just the new Outlook-paste feature.

from types import SimpleNamespace

from app.ticketing.schemas.payloads import EmailPayload, OutboundEnvelope
from app.ticketing.services.graph_client import (
    _build_graph_attachments,
    _build_reply_action_body,
    _build_send_mail_message,
    _plain_text_to_html_comment,
)


def _envelope(**overrides) -> OutboundEnvelope:
    base = dict(
        from_email="ticketing@probeps.com",
        to_email="patient@example.com",
        subject="Question about my visit",
        message_id="<abc123@probeps.com>",
        body="Plain text body.",
    )
    base.update(overrides)
    return OutboundEnvelope(**base)


def _attachment(**overrides):
    base = dict(
        filename="notes.txt",
        content_type="text/plain",
        content_base64="aGVsbG8=",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------
# _build_graph_attachments
# ---------------------------------------------------------


def test_build_graph_attachments_omits_inline_keys_for_ordinary_attachment():
    """
    Every attachment that has ever existed before this feature has
    is_inline=False/content_id=None — the resulting dict must be
    exactly the same four keys as before, never isInline/contentId
    even as null/false.
    """

    result = _build_graph_attachments([_attachment()])

    assert result == [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": "notes.txt",
            "contentType": "text/plain",
            "contentBytes": "aGVsbG8=",
        }
    ]
    assert "isInline" not in result[0]
    assert "contentId" not in result[0]


def test_build_graph_attachments_sets_inline_keys_when_present():
    result = _build_graph_attachments(
        [_attachment(is_inline=True, content_id="cid-abc-123")]
    )

    assert result[0]["isInline"] is True
    assert result[0]["contentId"] == "cid-abc-123"


def test_build_graph_attachments_does_not_mark_inline_without_a_content_id():
    """
    is_inline=True with no content_id is a malformed/incomplete state
    that should never actually occur (content_id is always minted
    alongside is_inline=True in AttachmentService.create_inline_image)
    — but if it ever did, this must not tell Graph a cid-less
    attachment is inline, which would be meaningless to Graph.
    """

    result = _build_graph_attachments([_attachment(is_inline=True, content_id=None)])

    assert "isInline" not in result[0]
    assert "contentId" not in result[0]


def test_build_graph_attachments_multiple_mixed_inline_and_ordinary():
    result = _build_graph_attachments(
        [
            _attachment(filename="a.pdf"),
            _attachment(filename="b.png", is_inline=True, content_id="cid-1"),
        ]
    )

    assert "isInline" not in result[0]
    assert result[1]["isInline"] is True
    assert result[1]["contentId"] == "cid-1"


# ---------------------------------------------------------
# _build_send_mail_message — body.contentType branching
# ---------------------------------------------------------


def test_build_send_mail_message_unchanged_when_body_html_absent():
    envelope = _envelope(body="Plain text body.")

    message = _build_send_mail_message(envelope)

    assert message["body"] == {"contentType": "Text", "content": "Plain text body."}


def test_build_send_mail_message_uses_html_when_body_html_present():
    envelope = _envelope(body="Plain fallback.", body_html="<p>Rich body.</p>")

    message = _build_send_mail_message(envelope)

    assert message["body"] == {"contentType": "HTML", "content": "<p>Rich body.</p>"}


def test_build_send_mail_message_recipients_cc_bcc_unaffected_by_body_html():
    envelope = _envelope(
        cc=["cc@example.com"],
        bcc=["bcc@example.com"],
        body_html="<p>hi</p>",
    )

    message = _build_send_mail_message(envelope)

    assert message["toRecipients"] == [{"emailAddress": {"address": "patient@example.com"}}]
    assert message["ccRecipients"] == [{"emailAddress": {"address": "cc@example.com"}}]
    assert message["bccRecipients"] == [{"emailAddress": {"address": "bcc@example.com"}}]


def test_build_send_mail_message_includes_attachments_with_inline_keys():
    envelope = _envelope(
        body_html='<p><img src="cid:cid-1"></p>',
        attachments=[
            {
                "filename": "screenshot.png",
                "content_type": "image/png",
                "content_base64": "aGVsbG8=",
                "content_id": "cid-1",
                "is_inline": True,
            }
        ],
    )

    message = _build_send_mail_message(envelope)

    assert message["attachments"][0]["isInline"] is True
    assert message["attachments"][0]["contentId"] == "cid-1"


# ---------------------------------------------------------
# _build_reply_action_body — the highest-risk asymmetric branch:
# Graph's reply/replyAll `comment` field has no contentType toggle at
# all, so body_html (already sanitized upstream) must be used AS-IS,
# never re-escaped through _plain_text_to_html_comment.
# ---------------------------------------------------------


def test_build_reply_action_body_unchanged_when_body_html_absent():
    envelope = _envelope(body="Line one.\nLine two.")

    result = _build_reply_action_body(envelope)

    assert result["comment"] == _plain_text_to_html_comment("Line one.\nLine two.")
    assert result["comment"] == "Line one.<br>Line two."


def test_build_reply_action_body_uses_raw_html_when_body_html_present():
    envelope = _envelope(
        body="Plain fallback with & and <tags>.",
        body_html="<p>Real <strong>HTML</strong> markup.</p>",
    )

    result = _build_reply_action_body(envelope)

    # Must be the html AS-IS — not run through _plain_text_to_html_comment,
    # which would double-escape it (turning "<strong>" into
    # "&lt;strong&gt;") and destroy the real markup.
    assert result["comment"] == "<p>Real <strong>HTML</strong> markup.</p>"
    assert "&lt;" not in result["comment"]


def test_build_reply_action_body_message_recipients_unaffected_by_body_html():
    envelope = _envelope(cc=["cc@example.com"], body_html="<p>hi</p>")

    result = _build_reply_action_body(envelope)

    assert result["message"]["toRecipients"] == [
        {"emailAddress": {"address": "patient@example.com"}}
    ]
    assert result["message"]["ccRecipients"] == [{"emailAddress": {"address": "cc@example.com"}}]

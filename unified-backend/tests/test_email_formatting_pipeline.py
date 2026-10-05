# test_email_formatting_pipeline.py
#
# Backend half of the composer's "editor == sent email" guarantee. The
# HTML below is byte-for-byte what the frontend submits as body_html for
# the spec's visual test message (see the matching
# "visual test message" case in unified-frontend's
# RichTextEditor.formatting.test.tsx, which pins the producing side):
# bold, italic, color, font size, indentation, numbered list, a
# right-aligned Shift+Enter signature line in Arial, the default
# Times New Roman 11pt wrapper and inline paragraph spacing.
#
# These tests confirm the formatting survives sanitize_outbound_html and
# reaches Microsoft Graph unchanged as an HTML body — for a fresh
# send (Compose/Forward), a threaded Reply/Reply All comment, and an
# internal note — while every XSS vector is still stripped. No DB, no
# network.

import re

import pytest

from app.ticketing.schemas.payloads import EmailPayload, OutboundEnvelope
from app.ticketing.services.email_envelope import build_compose_envelope, build_reply_envelope
from app.ticketing.services.graph_client import _build_reply_action_body, _build_send_mail_message
from app.ticketing.utils.html_sanitizer import sanitize_inbound_html, sanitize_outbound_html

VISUAL_TEST_BODY_HTML = (
    "<div data-utms-email-body=\"\" style=\"font-family:'Times New Roman', Times, serif;font-size:11pt;line-height:1.35;color:#000000\">"
    '<p style="margin-top:0;margin-bottom:10px"><strong>Hello Team,</strong></p>'
    '<p style="margin-top:0;margin-bottom:10px">We have reviewed the claim and <span style="color: rgb(192, 0, 0);"><em>identified the issue</em></span>.</p>'
    '<p style="margin-left:40px;margin-top:0;margin-bottom:10px"><span style="font-size: 14pt;">Please complete the following:</span></p>'
    '<ol style="margin-top:0;margin-bottom:10px;list-style-type:decimal">'
    '<li style="margin-top:0;margin-bottom:0"><p style="margin-top:0;margin-bottom:0">Verify the corrected claim.</p></li>'
    '<li style="margin-top:0;margin-bottom:0"><p style="margin-top:0;margin-bottom:0">Update the patient information.</p></li>'
    '<li style="margin-top:0;margin-bottom:0"><p style="margin-top:0;margin-bottom:0"><strong>Confirm the revised amount.</strong></p></li></ol>'
    '<p style="text-align:right;margin-top:0;margin-bottom:10px">Regards,<br><span style="font-family: Arial, Helvetica, sans-serif;">Hari Krishna</span></p>'
    "</div>"
)


def _declarations(html: str) -> list[set[str]]:
    """Every style attribute in document order, as a set of normalized declarations."""
    result = []
    for style in re.findall(r'style="([^"]*)"', html.replace("&quot;", '"')):
        result.append(
            {
                re.sub(r"\s*:\s*", ":", decl.strip()).replace(", ", ",")
                for decl in style.split(";")
                if decl.strip()
            }
        )
    return result


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def test_visual_test_message_survives_outbound_sanitization_unchanged():
    sanitized = sanitize_outbound_html(VISUAL_TEST_BODY_HTML)

    # Every inline style declaration (font, size, color, margins,
    # indent, alignment, list style) is kept, in order.
    assert _declarations(sanitized) == _declarations(VISUAL_TEST_BODY_HTML)
    # Structure and text are untouched.
    for tag in ("<strong>", "<em>", "<ol", "<li", "<br>", "<span"):
        assert sanitized.count(tag) == VISUAL_TEST_BODY_HTML.count(tag), tag
    assert _text(sanitized) == _text(VISUAL_TEST_BODY_HTML)
    # Only the frontend's own data- marker is dropped.
    assert "data-utms-email-body" not in sanitized


def test_visual_test_message_reaches_graph_as_html_for_compose_and_forward():
    envelope = build_compose_envelope(
        from_email="ticketing@probeps.com",
        to_email="patient@example.com",
        subject="Claim update",
        body="Hello Team,\nWe have reviewed the claim...",
        body_html=VISUAL_TEST_BODY_HTML,
    )

    message = _build_send_mail_message(envelope)

    assert message["body"]["contentType"] == "HTML"
    assert message["body"]["content"] == sanitize_outbound_html(VISUAL_TEST_BODY_HTML)
    assert "font-size:14pt" in message["body"]["content"]
    assert "margin-left:40px" in message["body"]["content"]


def test_visual_test_message_reaches_graph_as_the_reply_comment():
    envelope = build_reply_envelope(
        from_email="ticketing@probeps.com",
        inbound_payload=EmailPayload(
            subject="Question about my visit",
            body="Hi, I had a question.",
            from_email="patient@example.com",
            to_email="ticketing@probeps.com",
        ),
        inbound_message_id="<original@example.com>",
        body="Hello Team,",
        body_html=VISUAL_TEST_BODY_HTML,
    )

    assert envelope is not None
    comment = _build_reply_action_body(envelope)["comment"]
    # Graph appends the quoted original message after this comment
    # itself — the reply's own formatting must arrive intact and
    # unescaped.
    assert comment == sanitize_outbound_html(VISUAL_TEST_BODY_HTML)
    assert "&lt;" not in comment
    assert "text-align:right" in comment


def test_plain_reply_fallback_unchanged_when_no_body_html():
    envelope = OutboundEnvelope(
        from_email="ticketing@probeps.com",
        to_email="patient@example.com",
        subject="Re: Question",
        message_id="<abc@probeps.com>",
        body="Line one\nLine two",
    )

    assert _build_send_mail_message(envelope)["body"] == {"contentType": "Text", "content": "Line one\nLine two"}


# ---------------------------------------------------------------
# Toolbar formatting each survives on its own
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "html",
    [
        '<p><span style="font-family:Georgia, serif;">font</span></p>',
        '<p><span style="font-size:18pt;">size</span></p>',
        '<p><span style="color:#ff0000;">color</span></p>',
        '<p><span style="background-color:#ffff00;">highlight</span></p>',
        "<p><s>strike</s></p>",
        '<p style="text-align:justify;">justify</p>',
        '<p style="margin-left:80px;">indent</p>',
        '<ul style="list-style-type:disc;"><li><p>a</p><ul style="list-style-type:circle;"><li><p>b</p></li></ul></li></ul>',
        '<blockquote style="margin:0 0 10px 0;padding-left:12px;border-left:2px solid #cccccc;color:#555555;"><p>q</p></blockquote>',
        '<p><a href="https://probeps.com" style="color:#0563c1;text-decoration:underline;">link</a></p>',
    ],
)
def test_supported_formatting_is_preserved(html):
    assert sanitize_outbound_html(html) == html


# ---------------------------------------------------------------
# Security — widening the outbound allow-list must not open XSS holes
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "style",
    [
        "background-image:url(https://evil.test/pixel.png)",
        "color:expression(alert(1))",
        "font-family:x;behavior:url(evil.htc)",
        "color:red\\;background:url(x)",
        "position:fixed;top:0;left:0;width:100%",
        "font-size:/*x*/12pt",
        "color:javascript:alert(1)",
    ],
)
def test_unsafe_or_unknown_css_is_dropped(style):
    result = sanitize_outbound_html(f'<p style="{style}">x</p><span style="{style}">y</span>')

    assert "url(" not in result
    assert "expression" not in result
    assert "javascript" not in result
    assert "position" not in result
    assert "behavior" not in result
    assert "/*" not in result


def test_event_handlers_scripts_and_javascript_urls_still_removed():
    result = sanitize_outbound_html(
        '<p style="color:#ff0000;" onclick="alert(1)" onmouseover="alert(2)">x</p>'
        '<span style="color:#ff0000;" onload="alert(3)">y</span>'
        '<a href="javascript:alert(1)" style="color:#0563c1;">z</a>'
        "<script>alert(4)</script><iframe src=\"https://evil.test\"></iframe>"
    )

    assert "on" + "click" not in result
    assert "onmouseover" not in result
    assert "onload" not in result
    assert "javascript:" not in result
    assert "<script" not in result
    assert "<iframe" not in result
    assert '<p style="color:#ff0000;">x</p>' in result


def test_style_is_never_allowed_on_images_or_table_cells():
    result = sanitize_outbound_html(
        '<p><img src="cid:abc" style="width:9999px"></p>'
        '<table><tr><td style="background-color:#ff0000;">a</td></tr></table>'
    )

    assert "9999" not in result
    assert "#ff0000" not in result
    # The server-owned cell styling is still applied exactly as before.
    assert '<td style="border:1px solid #888888;padding:6px 8px;text-align:left;">a</td>' in result


def test_inbound_sender_html_keeps_the_original_narrow_allow_list():
    result = sanitize_inbound_html(
        '<p style="color:#ff0000;text-align:center;">x</p><span style="color:red;">y</span><s>z</s>'
    )

    assert "style=" not in result
    assert "<span" not in result
    assert "<s>" not in result

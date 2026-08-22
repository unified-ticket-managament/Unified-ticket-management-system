# test_html_sanitizer.py
#
# Pure-logic coverage for app.ticketing.utils.html_sanitizer.
# sanitize_outbound_html — the one server-side sanitization choke
# point for agent-authored body_html (Outlook-style clipboard paste)
# before it's ever embedded in a real outbound Graph HTML email. No
# DB, no network.

from app.ticketing.utils.html_sanitizer import sanitize_outbound_html


def test_allows_basic_formatting_tags():
    html = "<p>Hello <strong>world</strong> <em>and</em> <u>friend</u></p>"

    assert sanitize_outbound_html(html) == html


def test_allows_lists():
    html = "<ul><li>one</li><li>two</li></ul>"

    assert sanitize_outbound_html(html) == html


def test_allows_a_real_table():
    html = "<table><tbody><tr><td>Name</td><td>Status</td></tr></tbody></table>"

    assert sanitize_outbound_html(html) == html


def test_strips_script_tags_entirely():
    result = sanitize_outbound_html("<p>hi</p><script>alert(1)</script>")

    assert "<script" not in result
    assert "alert" not in result
    assert "<p>hi</p>" in result


def test_strips_javascript_href():
    result = sanitize_outbound_html('<a href="javascript:alert(1)">click</a>')

    assert "javascript:" not in result


def test_strips_event_handler_attributes():
    result = sanitize_outbound_html('<p onclick="evil()">hi</p>')

    assert "onclick" not in result
    assert "evil()" not in result


def test_strips_iframe_and_object_and_embed():
    result = sanitize_outbound_html(
        '<iframe src="https://evil.com"></iframe>'
        '<object data="x.swf"></object>'
        '<embed src="x.swf">'
    )

    assert "<iframe" not in result
    assert "<object" not in result
    assert "<embed" not in result


def test_preserves_a_cid_referenced_inline_image():
    html = '<p>Screenshot:</p><img src="cid:abc123" alt="screenshot">'

    result = sanitize_outbound_html(html)

    assert 'src="cid:abc123"' in result
    assert 'alt="screenshot"' in result


def test_strips_an_arbitrary_remote_image_src():
    """
    A real file attachment is how sharing an external image is meant
    to work in this feature — an inline <img> pointed at an arbitrary
    remote URL is a tracking-pixel/exfiltration vector, out of scope
    for pasted-screenshot support, and must never survive sanitization.
    """

    result = sanitize_outbound_html('<img src="https://evil.com/track.png">')

    assert "<img" not in result
    assert "evil.com" not in result


def test_strips_a_data_url_image_src():
    result = sanitize_outbound_html(
        '<img src="data:image/png;base64,AAAA">'
    )

    assert "<img" not in result


def test_strips_style_attributes():
    result = sanitize_outbound_html('<p style="background:url(javascript:alert(1))">hi</p>')

    assert "style=" not in result
    assert "javascript:" not in result


def test_table_structure_survives_excel_style_verbose_markup():
    """
    Excel's own clipboard HTML is much more verbose than this (mso-*
    spans, colgroup, o:p namespace tags, conditional comments) — this
    is a simplified stand-in confirming the *shape* (verbose wrapper
    tags stripped, real table structure kept) survives correctly.
    """

    html = (
        '<table border="1" cellspacing="0"><colgroup><col></colgroup>'
        '<tr><td><span style="mso-number-format:General">Raju</span></td>'
        "<td>Open</td></tr></table>"
    )

    result = sanitize_outbound_html(html)

    assert "<table>" in result
    assert "<td>Raju</td>" in result
    assert "<td>Open</td>" in result
    assert "colgroup" not in result
    assert "mso-" not in result


def test_empty_and_plain_text_only_html_pass_through_unchanged():
    assert sanitize_outbound_html("") == ""
    assert sanitize_outbound_html("<p>Just plain text.</p>") == "<p>Just plain text.</p>"

# test_html_sanitizer.py
#
# Pure-logic coverage for app.ticketing.utils.html_sanitizer.
# sanitize_outbound_html — the one server-side sanitization choke
# point for agent-authored body_html (Outlook-style clipboard paste)
# before it's ever embedded in a real outbound Graph HTML email — and
# sanitize_inbound_html, the sibling choke point for an external
# sender's own HTML (see the "nested-table border regression" section
# at the bottom of this file). No DB, no network.

from app.ticketing.utils.html_sanitizer import sanitize_inbound_html, sanitize_outbound_html


def test_allows_basic_formatting_tags():
    html = "<p>Hello <strong>world</strong> <em>and</em> <u>friend</u></p>"

    assert sanitize_outbound_html(html) == html


def test_allows_lists():
    html = "<ul><li>one</li><li>two</li></ul>"

    assert sanitize_outbound_html(html) == html


def test_allows_a_real_table():
    """
    The table's structure/content survives unchanged — border styling
    (see the _style_email_tables tests below) is layered on top of
    this, not a replacement for it, so this only asserts shape/content,
    not a byte-for-byte match (see test_table_border_styling.py-style
    assertions further down for the actual styling behavior).
    """

    html = "<table><tbody><tr><td>Name</td><td>Status</td></tr></tbody></table>"

    result = sanitize_outbound_html(html)

    assert "<tbody><tr>" in result
    assert "Name</td>" in result
    assert "Status</td>" in result
    assert "</tr></tbody></table>" in result


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

    assert "Raju</td>" in result
    assert "Open</td>" in result
    assert "colgroup" not in result
    assert "mso-" not in result


def test_empty_and_plain_text_only_html_pass_through_unchanged():
    assert sanitize_outbound_html("") == ""
    assert sanitize_outbound_html("<p>Just plain text.</p>") == "<p>Just plain text.</p>"


# ---------------------------------------------------------
# Outlook table border styling (_style_email_tables)
# ---------------------------------------------------------
#
# Outlook (and most real email clients) render a <table> with no
# border styling at all as a borderless grid, even though nh3's
# allow-list never lets a pasted style/border attribute survive in the
# first place — so this app must apply its own fixed inline styling
# rather than trust/preserve anything the agent pasted.


def test_table_gets_border_collapse_style():
    html = "<table><tr><td>a</td></tr></table>"

    result = sanitize_outbound_html(html)

    assert '<table style="border-collapse:collapse;width:100%;">' in result


def test_td_and_th_get_visible_border_and_padding():
    html = "<table><thead><tr><th>Role</th></tr></thead><tbody><tr><td>Staff</td></tr></tbody></table>"

    result = sanitize_outbound_html(html)

    assert '<th style="border:1px solid #888888;padding:6px 8px;text-align:left;">Role</th>' in result
    assert '<td style="border:1px solid #888888;padding:6px 8px;text-align:left;">Staff</td>' in result


def test_table_styling_preserves_colspan_rowspan():
    html = '<table><tr><td colspan="2">merged</td></tr></table>'

    result = sanitize_outbound_html(html)

    assert 'colspan="2"' in result
    assert "merged" in result


def test_table_styling_does_not_touch_non_table_tags():
    html = "<p>hi</p><ul><li>one</li></ul>"

    result = sanitize_outbound_html(html)

    assert result == html


def test_a_composer_resized_table_width_survives_and_is_used_in_the_style():
    """
    A whole-table resize in the composer produces a plain width="N"
    HTML attribute on <table> (see RichTextEditor.tsx's ResizableTable
    extension) — this must survive nh3.clean and _style_email_tables
    must build the injected style from it instead of hardcoding 100%,
    or the resize would be silently thrown away before ever reaching
    Outlook or storage.
    """

    html = '<table width="320"><tr><td>a</td><td>b</td></tr></table>'

    result = sanitize_outbound_html(html)

    assert 'width="320"' in result
    assert "width:320px" in result
    assert "width:100%" not in result


def test_a_table_with_no_explicit_width_still_defaults_to_100_percent():
    html = "<table><tr><td>a</td></tr></table>"

    result = sanitize_outbound_html(html)

    assert 'width="320"' not in result
    assert "width:100%" in result


def test_colgroup_and_col_are_stripped_from_outbound_tables():
    """
    Column resizing is real (see the composer's ColumnResize plugin),
    but is deliberately implemented as a plain width="N" attribute on
    each <td>/<th> rather than <colgroup>/<col> — Outlook's Word
    rendering engine doesn't reliably honor colgroup/col widths.
    Confirms those tags stay off the allow-list even if a future
    composer change ever emitted them.
    """

    html = '<table><colgroup><col style="width:50px"></colgroup><tr><td>a</td></tr></table>'

    result = sanitize_outbound_html(html)

    assert "<colgroup" not in result
    assert "<col" not in result


def test_a_composer_resized_column_width_survives_and_is_used_in_the_style():
    """
    Per-column resize in the composer produces a plain width="N" HTML
    attribute on the affected <td>/<th> cells (see RichTextEditor.tsx's
    ColumnResize extension) — mirrors the whole-table-width test above,
    just at the cell level.
    """

    html = '<table><tr><td width="220">a</td><td>b</td></tr></table>'

    result = sanitize_outbound_html(html)

    assert 'width="220"' in result
    assert "width:220px" in result


def test_a_cell_with_no_explicit_width_keeps_the_base_cell_style():
    html = "<table><tr><td>a</td></tr></table>"

    result = sanitize_outbound_html(html)

    assert '<td style="border:1px solid #888888;padding:6px 8px;text-align:left;">a</td>' in result


def test_a_resized_image_width_and_height_survive():
    html = '<img src="cid:abc123" width="200" height="100" alt="screenshot">'

    result = sanitize_outbound_html(html)

    assert 'width="200"' in result
    assert 'height="100"' in result


def test_table_styling_and_cid_image_coexist():
    html = (
        "<table><tr><td>Screenshot</td></tr></table>"
        '<img src="cid:abc123" alt="screenshot">'
    )

    result = sanitize_outbound_html(html)

    assert 'src="cid:abc123"' in result
    assert "border-collapse:collapse" in result


# ---------------------------------------------------------
# Nested-table border regression: inbound mail must not get the
# outbound composer's border styling (sanitize_inbound_html)
# ---------------------------------------------------------
#
# sanitize_outbound_html's `_style_email_tables` step is correct for
# agent-authored content (every <table> there is a deliberate pasted
# data table), but an external sender's inbound HTML routinely uses
# nested <table> elements purely for layout (newsletter/marketing
# templates positioning a header/columns/footer, exactly like the
# reported Sunshine Health regression) — those must render exactly as
# the sender sent them, with no border ever added.


def test_a_real_pasted_data_table_still_gets_visible_borders_outbound():
    """
    Requirement: a data table created/pasted from UTMS's own composer
    (reply/compose/internal note — every sanitize_outbound_html caller)
    must still render with visible borders in Outlook.
    """

    html = "<table><tr><td>Name</td><td>Status</td></tr><tr><td>Raju</td><td>Open</td></tr></table>"

    result = sanitize_outbound_html(html)

    assert "border-collapse:collapse" in result
    assert 'border:1px solid #888888' in result


def test_inbound_sender_html_does_not_get_border_styling():
    """
    Requirement: incoming marketing/layout emails containing nested
    tables must not suddenly show borders around every layout
    container. sanitize_inbound_html (mail_mapping_service.py's own
    choke point for external sender HTML) must never add the
    `_style_email_tables` styling sanitize_outbound_html applies.
    """

    html = (
        "<table><tr><td>"
        "<table><tr><td>"
        "<table><tr><td>Sunshine Health newsletter content</td></tr></table>"
        "</td></tr></table>"
        "</td></tr></table>"
    )

    result = sanitize_inbound_html(html)

    assert "border" not in result
    assert "style=" not in result
    assert "Sunshine Health newsletter content" in result
    # The nested table structure itself is preserved, not flattened.
    assert result.count("<table>") == 3


def test_inbound_sanitizer_still_strips_dangerous_content():
    """
    sanitize_inbound_html must not be a weaker sanitizer than
    sanitize_outbound_html for anything except table border styling —
    an external sender's HTML is no more trustworthy than a pasted one.
    """

    html = (
        '<table><tr><td onclick="evil()">click</td></tr></table>'
        "<script>alert(1)</script>"
        '<img src="https://evil.com/track.png">'
        '<a href="javascript:alert(1)">bad link</a>'
    )

    result = sanitize_inbound_html(html)

    assert "onclick" not in result
    assert "evil()" not in result
    assert "<script" not in result
    assert "alert" not in result
    assert "evil.com" not in result
    assert "javascript:" not in result
    assert "click</td>" in result
    assert "bad link" in result


def test_inbound_sanitizer_preserves_cid_inline_images():
    html = '<p>See attached:</p><img src="cid:xyz789" alt="chart">'

    result = sanitize_inbound_html(html)

    assert 'src="cid:xyz789"' in result
    assert 'alt="chart"' in result


# ---------------------------------------------------------
# Genuine inbound data tables: the other half of the table-border
# regression. An external sender's <table> is judged on its own shape
# (_is_genuine_data_table) rather than being blanket-excluded — a real
# 2+ row, 2+ column table (an invoice, a status report) must still get
# a visible grid even though it arrived inbound, while a layout/
# wrapper table (the case above) still gets none.
# ---------------------------------------------------------


def test_a_genuine_flat_inbound_table_now_gets_visible_borders():
    html = "<table><tr><td>Name</td><td>Status</td></tr><tr><td>Raju</td><td>Open</td></tr></table>"

    result = sanitize_inbound_html(html)

    assert "border-collapse:collapse" in result
    assert "border:1px solid #888888" in result
    assert "Raju</td>" in result
    assert "Status</td>" in result


def test_inbound_single_column_multi_row_table_stays_unstyled():
    """
    Known, accepted limitation: a single-column table (rows stacked
    vertically) is structurally identical to the classic layout
    pattern used to stack a header/body/footer, so it is never treated
    as a data table, regardless of row count.
    """

    html = "<table><tr><td>Item A</td></tr><tr><td>Item B</td></tr><tr><td>Item C</td></tr></table>"

    result = sanitize_inbound_html(html)

    assert "border" not in result
    assert "style=" not in result


def test_inbound_genuine_table_nested_inside_a_layout_wrapper_is_styled_independently():
    """
    A real data table pasted inside an outer layout/wrapper table (a
    common newsletter pattern: single-cell wrapper for margins, with
    the actual content table inside it) must get borders on the inner
    table only — the outer 1x1 wrapper must stay untouched.
    """

    html = (
        "<table><tr><td>"
        "<table><tr><td>Name</td><td>Status</td></tr><tr><td>Raju</td><td>Open</td></tr></table>"
        "</td></tr></table>"
    )

    result = sanitize_inbound_html(html)

    assert result.count("border-collapse:collapse") == 1
    assert result.count("<table>") == 1  # the outer 1x1 wrapper stays bare
    assert result.count("<table style=") == 1  # only the inner table was styled
    assert "Raju</td>" in result


def test_inbound_table_with_header_and_single_data_row_gets_styled():
    html = (
        "<table><thead><tr><th>Name</th><th>Status</th></tr></thead>"
        "<tbody><tr><td>Raju</td><td>Open</td></tr></tbody></table>"
    )

    result = sanitize_inbound_html(html)

    assert "border-collapse:collapse" in result
    assert result.count("border:1px solid #888888") == 4  # 2 <th> + 2 <td>


def test_inbound_excel_clipboard_table_still_gets_styled_despite_stripped_markup():
    """
    Real Excel-clipboard HTML carries border/cellspacing/colgroup
    markup that nh3 already strips outright (see
    test_table_structure_survives_excel_style_verbose_markup) — the
    classifier runs on the post-nh3 structure, so a genuine 2-row
    table still qualifies for styling even once all of that is gone.
    """

    html = (
        '<table border="1" cellspacing="0"><colgroup><col></colgroup>'
        '<tr><td><span style="mso-number-format:General">Raju</span></td>'
        "<td>Open</td></tr>"
        "<tr><td>Suresh</td><td>Closed</td></tr></table>"
    )

    result = sanitize_inbound_html(html)

    assert "colgroup" not in result
    assert "mso-" not in result
    assert "<span" not in result  # not an allowed tag either
    assert "border-collapse:collapse" in result
    assert "Raju" in result
    assert "Suresh</td>" in result


def test_inbound_table_styling_does_not_reintroduce_html_body_wrapper():
    """
    The classifier reparses/reserializes the whole fragment through
    BeautifulSoup — must not wrap a bare fragment in a stray
    <html>/<body>, which would corrupt everything downstream that
    stores/renders body_html as a fragment, not a full document.
    """

    html = "<p>Hello &amp; welcome</p><table><tr><td>A</td><td>B</td></tr><tr><td>1</td><td>2</td></tr></table>"

    result = sanitize_inbound_html(html)

    assert "<html" not in result
    assert "<body" not in result
    assert "Hello &amp; welcome" in result

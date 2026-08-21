# test_named_link_preservation.py
#
# Pure-logic coverage for mail_mapping_service._html_to_plain_text's
# named-link handling — a real, reported bug: Outlook's Insert > Link
# feature lets a sender give a link a custom display label (e.g.
# "link") distinct from the URL itself. A plain BeautifulSoup
# get_text() keeps only that label and silently discards the href
# entirely, leaving an inert, unclickable word with no way to reach
# the real destination. No database needed.

from app.ticketing.services.mail_mapping_service import _html_to_plain_text


def _normalized(html: str) -> str:
    # get_text(separator="\n") inserts a newline at every tag
    # boundary (not just block-level ones) — a pre-existing,
    # unrelated convention this file doesn't test. Collapsing
    # whitespace keeps these assertions about the named-link
    # rewrite itself, not about that separator behavior.
    return " ".join(_html_to_plain_text(html).split())


def test_named_link_preserves_the_real_url_alongside_its_label():
    html = (
        '<html><body>Check this out: '
        '<a href="https://console.neon.tech/app/projects/tables">link</a>'
        "</body></html>"
    )

    assert (
        _normalized(html)
        == "Check this out: link (https://console.neon.tech/app/projects/tables)"
    )


def test_named_link_behind_outlook_safe_links_prefers_originalsrc():
    """
    Outlook Safe Links rewrites href to a safelinks.protection.
    outlook.com tracking redirect and puts the real destination in
    originalsrc instead — using href here would preserve an ugly,
    short-lived tracking URL rather than the real one.
    """

    html = (
        '<html><body>Check this out: '
        '<a href="https://ind01.safelinks.protection.outlook.com/?url=xyz" '
        'originalsrc="https://console.neon.tech/app/projects/tables">link</a>'
        "</body></html>"
    )

    assert (
        _normalized(html)
        == "Check this out: link (https://console.neon.tech/app/projects/tables)"
    )


def test_bare_auto_linked_url_is_not_duplicated():
    """
    When Outlook auto-linkifies a pasted URL, the visible label is
    already the URL itself — nothing is lost, so this must not
    rewrite it into a redundant "url (url)".
    """

    html = (
        '<html><body>Testing '
        '<a href="https://console.neon.tech/app/projects/tables">'
        "https://console.neon.tech/app/projects/tables</a></body></html>"
    )

    assert _normalized(html) == "Testing https://console.neon.tech/app/projects/tables"


def test_cloud_storage_link_is_left_for_extract_cloud_link_attachments_to_handle():
    """
    A OneDrive/SharePoint share link is surfaced separately as a
    linked attachment (extract_cloud_link_attachments) — this
    rewrite must not also duplicate the URL inline here.
    """

    html = (
        '<html><body>'
        '<a href="https://contoso-my.sharepoint.com/x/report.pdf">report.pdf</a>'
        "</body></html>"
    )

    assert _normalized(html) == "report.pdf"


def test_anchor_with_no_visible_text_falls_back_to_the_url_itself():
    html = '<html><body><a href="https://console.neon.tech/app/projects/tables"></a></body></html>'

    assert _normalized(html) == "https://console.neon.tech/app/projects/tables"


def test_relative_and_mailto_links_are_left_untouched():
    html = (
        '<html><body>See <a href="/internal/page">this page</a> or email '
        '<a href="mailto:someone@example.com">someone</a></body></html>'
    )

    assert _normalized(html) == "See this page or email someone"

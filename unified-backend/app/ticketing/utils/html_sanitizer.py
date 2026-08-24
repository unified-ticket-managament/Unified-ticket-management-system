# html_sanitizer.py
#
# The one server-side sanitization choke point for agent-authored
# `body_html` (Outlook-style clipboard paste — pasted rich text/
# tables/inline images) before it is ever embedded into a real
# outbound Microsoft Graph HTML email. No sanitizer existed anywhere
# in this backend before this feature; this is deliberately narrow —
# an allow-list matching exactly what the composer's paste feature
# needs, not a general-purpose HTML cleaner.
#
# img[src] is restricted to `cid:...` references only (an inline
# image this platform itself uploaded and is embedding — see
# attachment_service.create_inline_image) — an arbitrary remote
# `<img src="https://...">` in a message body is a tracking-pixel/
# exfiltration vector that is out of this feature's scope entirely
# (sharing an external image is what a real file attachment is for).

import re

import nh3

_ALLOWED_TAGS = {
    "p", "br", "div",
    "b", "strong", "i", "em", "u",
    "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "td", "th",
    "a", "img",
}

_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}

# "cid" must be included here or nh3 strips the whole src="cid:..."
# attribute outright (confirmed directly against the installed nh3
# build — an unrecognized URL scheme on a filtered attribute is
# dropped, not merely left un-rel'd) since nh3's own scheme allow-list
# has no concept of "this one scheme is fine on img but not a" — the
# real per-tag restriction (only cid: may appear on <img src>, never
# http(s)) is enforced afterward by _strip_non_cid_images below, not
# by this set.
_ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "cid"}


def sanitize_outbound_html(html: str) -> str:
    """
    Strips everything outside the allow-list above (script tags,
    event-handler attributes, javascript: URLs, iframes/objects/
    embeds, style attributes, arbitrary remote images, etc.) before
    `body_html` is allowed to reach an OutboundEnvelope. Called once,
    from email_envelope.py, rather than at every individual caller.

    Also applies `_style_email_tables` (see below) — every caller of
    this function is agent-authored content (a composer paste, a reply,
    an internal note), where a <table> is always a genuine, deliberate
    data table the agent pasted in, never structural/layout markup.
    """

    return _style_email_tables(_clean_html(html))


def sanitize_inbound_html(html: str) -> str:
    """
    Sanitizes an external sender's own HTML for storage/display — the
    same tag/attribute/scheme allow-list and cid-only <img> restriction
    as sanitize_outbound_html, but deliberately does NOT run
    `_style_email_tables`. An inbound sender's <table> is just as often
    pure layout/positioning markup (newsletter/marketing templates
    nest tables purely to lay out a header/columns/footer, with no
    intent for any of it to look like a bordered grid) as it is a real
    data table — unlike agent-authored content, where every <table> is
    a deliberate paste. Forcing a visible border onto every nested
    layout table made ordinary marketing/notification emails render as
    a wall of boxes never present in the original message (confirmed
    against a real inbound Sunshine Health email). Preserving the
    sender's own structure/formatting is the priority for inbound mail;
    only genuinely dangerous content is stripped.
    """

    return _clean_html(html)


def _clean_html(html: str) -> str:
    cleaned = nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes=_ALLOWED_URL_SCHEMES,
        link_rel=None,
    )

    return _strip_non_cid_images(cleaned)


def _strip_non_cid_images(html: str) -> str:
    """
    nh3's url_schemes only governs schemes it recognizes as URLs at
    all (http/https/mailto above) — a `cid:` reference isn't a
    "dangerous" scheme nh3 needs to block, so it already survives
    nh3.clean unchanged. This second pass removes any `<img>` whose
    `src` is NOT a `cid:` reference (e.g. a bare/relative src, or one
    of the allowed http(s) schemes leaking onto an <img> specifically)
    — real file sharing goes through a proper attachment, never an
    inline remote image in the body.
    """

    def _drop_if_not_cid(match: "re.Match[str]") -> str:
        tag = match.group(0)
        src_match = re.search(r'src\s*=\s*"([^"]*)"', tag, re.IGNORECASE)
        if src_match and src_match.group(1).lower().startswith("cid:"):
            return tag
        return ""

    return re.sub(r"<img\b[^>]*/?>", _drop_if_not_cid, html, flags=re.IGNORECASE)


# Outlook (and most real email clients) render a <table> with no
# border styling at all as a borderless grid, even though this app's
# own read-view CSS makes the exact same markup look fine in-app — the
# gap only shows up once a message actually reaches a real inbox.
# Inline styles are required (not a <style> block) for Outlook
# compatibility. Applied unconditionally, not merged with any existing
# style attribute — nh3.clean above never allows one through in the
# first place (see _ALLOWED_ATTRIBUTES), so there is never a pasted
# style attribute here to preserve or conflict with.
_TABLE_STYLE = "border-collapse:collapse;width:100%;"
_CELL_STYLE = "border:1px solid #888888;padding:6px 8px;text-align:left;"


def _style_email_tables(html: str) -> str:
    html = re.sub(r"<table\b", f'<table style="{_TABLE_STYLE}"', html, flags=re.IGNORECASE)
    html = re.sub(
        r"<(td|th)\b",
        lambda match: f'<{match.group(1)} style="{_CELL_STYLE}"',
        html,
        flags=re.IGNORECASE,
    )
    return html

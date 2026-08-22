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
    """

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

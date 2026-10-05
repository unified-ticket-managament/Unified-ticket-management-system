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
from bs4 import BeautifulSoup, Tag

# nh3 unwraps a disallowed tag rather than dropping its content — a
# heading or blockquote missing from this set doesn't disappear, it
# collapses into the surrounding flow with no block boundary at all
# (e.g. "<h2>Action needed</h2><p>...</p>" becomes one run of text with
# no separation), which is indistinguishable from real body text losing
# its formatting. h1-h6/blockquote are common in real inbound sender
# HTML (an external sender's own formatting, not something this app's
# composer produces) and blockquote is also what buildForwardHtml
# (frontend richText.ts) and the composer's own Blockquote toolbar
# button already wrap outbound quoted/forwarded content in — both were
# silently losing that wrapper before this fix.
_ALLOWED_TAGS = {
    "p", "br", "div",
    "b", "strong", "i", "em", "u",
    "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote",
    "table", "thead", "tbody", "tr", "td", "th",
    "a", "img",
}

_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href"},
    "img": {"src", "alt", "width", "height"},
    "table": {"width"},
    "td": {"colspan", "rowspan", "width"},
    "th": {"colspan", "rowspan", "width"},
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

# Outbound-only additions for the composer's Outlook-style formatting
# toolbar (font family/size, text color, highlight, alignment,
# indentation, strikethrough — see the frontend's lib/emailHtml.ts,
# which also inlines paragraph spacing and the default font at send
# time). Email clients ignore <style> blocks/classes far too often, so
# this formatting can only survive as inline `style` — allowed here on
# text/block tags and links only, never on table/td/th
# (_style_email_tables below still owns those, unconditionally) and
# never on img. Inbound
# sender HTML keeps the original narrower allow-list above, unchanged.
_OUTBOUND_STYLED_TAGS = {
    "p", "div", "span", "li", "ul", "ol", "blockquote", "a",
    "h1", "h2", "h3", "h4", "h5", "h6",
}
_OUTBOUND_ALLOWED_TAGS = _ALLOWED_TAGS | {"span", "s"}
_OUTBOUND_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    **_ALLOWED_ATTRIBUTES,
    **{tag: _ALLOWED_ATTRIBUTES.get(tag, set()) | {"style"} for tag in _OUTBOUND_STYLED_TAGS},
}

# Per-property value grammar — deliberately strict: anything that
# doesn't match (url(), expression(), escapes, comments, @-rules, or
# just an unexpected shape) drops that one declaration, and a style
# attribute left with no valid declarations is dropped entirely.
_CSS_LENGTH = r"-?\d+(?:\.\d+)?(?:px|pt|em|rem|%)?"
_CSS_COLOR = r"#[0-9a-f]{3,8}|rgba?\(\s*[\d.\s,%]+\)|[a-z]{3,20}"
_CSS_PROPERTY_PATTERNS: dict[str, "re.Pattern[str]"] = {
    name: re.compile(rf"^(?:{pattern})$", re.IGNORECASE)
    for name, pattern in {
        "color": _CSS_COLOR,
        "background-color": _CSS_COLOR,
        "font-family": r"[\w\s,'\"-]{1,200}",
        "font-size": r"\d+(?:\.\d+)?(?:px|pt|em|rem|%)|xx-small|x-small|small|medium|large|x-large|xx-large",
        "font-weight": r"normal|bold|bolder|lighter|[1-9]00",
        "font-style": r"normal|italic|oblique",
        "text-decoration": r"[a-z\s-]{1,60}",
        "text-decoration-line": r"[a-z\s-]{1,60}",
        "text-align": r"left|right|center|justify|start|end",
        "line-height": rf"normal|{_CSS_LENGTH}",
        "margin": rf"(?:{_CSS_LENGTH}|auto)(?:\s+(?:{_CSS_LENGTH}|auto)){{0,3}}",
        "margin-top": rf"{_CSS_LENGTH}|auto",
        "margin-right": rf"{_CSS_LENGTH}|auto",
        "margin-bottom": rf"{_CSS_LENGTH}|auto",
        "margin-left": rf"{_CSS_LENGTH}|auto",
        "padding-left": _CSS_LENGTH,
        "border-left": rf"\d+(?:\.\d+)?(?:px|pt)\s+(?:solid|dashed|dotted)\s+(?:{_CSS_COLOR})",
        "list-style-type": r"disc|circle|square|decimal|lower-alpha|upper-alpha|lower-roman|upper-roman|none",
    }.items()
}


def _filter_style_value(style: str) -> str | None:
    kept: list[str] = []
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        name, _, value = declaration.partition(":")
        name = name.strip().lower()
        value = re.sub(r"\s*!important\s*$", "", value.strip(), flags=re.IGNORECASE)
        pattern = _CSS_PROPERTY_PATTERNS.get(name)
        if pattern is None or not value or not pattern.match(value):
            continue
        kept.append(f"{name}:{value}")
    return ";".join(kept) + ";" if kept else None


def _outbound_attribute_filter(tag: str, attribute: str, value: str) -> str | None:
    if attribute == "style":
        return _filter_style_value(value)
    return value


_SPAN_TOKEN = re.compile(r"<span(?:\s[^>]*)?>|</span>", re.IGNORECASE)


def _unwrap_bare_spans(html: str) -> str:
    """
    A pasted <span> whose every style declaration was filtered out
    (e.g. Excel's mso-number-format) is a meaningless wrapper — remove
    it (keeping its content) so outbound markup stays as clean as it
    was before <span> was allowed at all. nh3's output is well-formed,
    so a simple open/close stack is enough to pair each tag.
    """
    if "<span" not in html:
        return html
    stack: list[bool] = []

    def _replace(match: "re.Match[str]") -> str:
        token = match.group(0)
        if token.startswith("</"):
            return "" if (stack.pop() if stack else True) else token
        bare = token.lower() == "<span>"
        stack.append(bare)
        return "" if bare else token

    return _SPAN_TOKEN.sub(_replace, html)


def sanitize_outbound_html(html: str) -> str:
    """
    Strips everything outside the allow-list above (script tags,
    event-handler attributes, javascript: URLs, iframes/objects/
    embeds, unsafe/unknown inline CSS, arbitrary remote images, etc.)
    before `body_html` is allowed to reach an OutboundEnvelope. Called once,
    from email_envelope.py, rather than at every individual caller.

    Also applies `_style_email_tables` (see below) — every caller of
    this function is agent-authored content (a composer paste, a reply,
    an internal note), where a <table> is always a genuine, deliberate
    data table the agent pasted in, never structural/layout markup.
    """

    cleaned = _clean_html(
        html,
        tags=_OUTBOUND_ALLOWED_TAGS,
        attributes=_OUTBOUND_ALLOWED_ATTRIBUTES,
        attribute_filter=_outbound_attribute_filter,
    )
    return _style_email_tables(_unwrap_bare_spans(cleaned))


def sanitize_inbound_html(html: str) -> str:
    """
    Sanitizes an external sender's own HTML for storage/display — the
    same tag/attribute/scheme allow-list and cid-only <img> restriction
    as sanitize_outbound_html, but deliberately does NOT run the blind,
    unconditional `_style_email_tables`. An inbound sender's <table> is
    just as often pure layout/positioning markup (newsletter/marketing
    templates nest tables purely to lay out a header/columns/footer,
    with no intent for any of it to look like a bordered grid) as it is
    a real data table — unlike agent-authored content, where every
    <table> is a deliberate paste. Forcing a visible border onto every
    nested layout table made ordinary marketing/notification emails
    render as a wall of boxes never present in the original message
    (confirmed against a real inbound Sunshine Health email).

    Instead, `_style_qualifying_inbound_tables` judges each <table> on
    its own shape and only borders the ones that actually look like
    data (see its docstring) — so a genuine table (e.g. an invoice or
    status report) still gets a visible grid, while layout/wrapper
    tables stay untouched. Preserving the sender's own structure is
    still the priority; only genuinely dangerous content is stripped.
    """

    return _style_qualifying_inbound_tables(_clean_html(html))


def _clean_html(
    html: str,
    tags: set[str] = _ALLOWED_TAGS,
    attributes: dict[str, set[str]] = _ALLOWED_ATTRIBUTES,
    attribute_filter=None,
) -> str:
    cleaned = nh3.clean(
        html,
        tags=tags,
        attributes=attributes,
        attribute_filter=attribute_filter,
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
# style attribute — nh3.clean above never allows one through on
# table/td/th in the first place (see _ALLOWED_ATTRIBUTES and
# _OUTBOUND_STYLED_TAGS), so there is never a pasted style attribute
# here to preserve or conflict with.
_TABLE_STYLE_BASE = "border-collapse:collapse;"
# Used unmodified by _style_qualifying_inbound_tables below (inbound
# tables have no resize concept — always the fixed 100% default).
_TABLE_STYLE = f"{_TABLE_STYLE_BASE}width:100%;"
_CELL_STYLE = "border:1px solid #888888;padding:6px 8px;text-align:left;"


def _style_email_tables(html: str) -> str:
    def _table_replacement(match: "re.Match[str]") -> str:
        tag = match.group(0)
        # A composer-driven table resize survives nh3.clean as a plain
        # width="N" HTML attribute (see _ALLOWED_ATTRIBUTES) — honor it
        # here instead of forcing every table to 100%, which would
        # silently undo the resize. No width attribute (every
        # non-resized/legacy table) keeps the original 100% default.
        width_match = re.search(r'width\s*=\s*"(\d+)"', tag, re.IGNORECASE)
        width_css = f"{width_match.group(1)}px" if width_match else "100%"
        style = f"{_TABLE_STYLE_BASE}width:{width_css};"
        return re.sub(r"^<table\b", f'<table style="{style}"', tag, flags=re.IGNORECASE)

    html = re.sub(r"<table\b[^>]*>", _table_replacement, html, flags=re.IGNORECASE)

    def _cell_replacement(match: "re.Match[str]") -> str:
        tag = match.group(0)
        tag_name = match.group(1)
        # A composer-driven column resize survives nh3.clean as a plain
        # width="N" HTML attribute on the cell itself (see
        # _ALLOWED_ATTRIBUTES) — fold it into the injected style too,
        # same as the table-width handling above, for the cell-width
        # equivalent of "don't silently undo the resize." No width
        # attribute (every non-resized/legacy cell) keeps the base style
        # unchanged, same as before this cell ever had a width concept.
        width_match = re.search(r'width\s*=\s*"(\d+)"', tag, re.IGNORECASE)
        style = f"{_CELL_STYLE}width:{width_match.group(1)}px;" if width_match else _CELL_STYLE
        return re.sub(rf"^<{tag_name}\b", f'<{tag_name} style="{style}"', tag, flags=re.IGNORECASE)

    html = re.sub(r"<(td|th)\b[^>]*>", _cell_replacement, html, flags=re.IGNORECASE)
    return html


def _closest_table(tag: Tag) -> Tag | None:
    parent = tag.parent
    while parent is not None:
        if getattr(parent, "name", None) == "table":
            return parent
        parent = parent.parent
    return None


def _table_own_rows(table: Tag) -> list[Tag]:
    # A <table> nested inside this one has its own <tr>s; walking up
    # from each <tr> to its nearest enclosing <table> is what keeps a
    # table's shape judged independently of anything nested inside (or
    # wrapping) it — see _is_genuine_data_table.
    return [tr for tr in table.find_all("tr") if _closest_table(tr) is table]


def _is_genuine_data_table(table: Tag) -> bool:
    """
    An inbound <table> only "counts" as real tabular data — and gets a
    visible grid — if it actually looks like one: at least 2 rows and
    at least 2 columns of its own. A single-column table (the classic
    vertical-stack layout pattern used to lay out a newsletter's
    header/body/footer as one <table> "row" per section) never
    qualifies, no matter how many rows it has — this is what keeps a
    Sunshine-Health-style nested layout table un-bordered while a real
    2-column status/invoice table gets styled.
    """
    own_rows = _table_own_rows(table)
    if len(own_rows) < 2:
        return False

    max_cols = max(
        (len(row.find_all(["td", "th"], recursive=False)) for row in own_rows),
        default=0,
    )
    return max_cols >= 2


def _style_qualifying_inbound_tables(html: str) -> str:
    """
    Inbound counterpart to `_style_email_tables`: rather than styling
    every <table> unconditionally (right for agent-authored content,
    wrong for an external sender's mail — see sanitize_inbound_html),
    each <table> is judged on its own shape via
    `_is_genuine_data_table`. Only a qualifying table's own cells are
    styled — a nested table inside (or wrapping) it is judged and
    styled independently, so a real data table nested inside a layout
    wrapper, or vice versa, never cross-contaminates the other.
    """
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        if not _is_genuine_data_table(table):
            continue
        table["style"] = _TABLE_STYLE
        for row in _table_own_rows(table):
            for cell in row.find_all(["td", "th"], recursive=False):
                cell["style"] = _CELL_STYLE
    return str(soup)

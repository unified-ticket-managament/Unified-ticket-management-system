# mail_mapping_service.py
#
# Converts a provider-shaped external email payload (today: a
# realistic Microsoft Graph `message` resource) into this service's
# own EmailRequest — the schema EmailService.receive_email already
# knows how to turn into an Interaction (client resolution,
# threading, audit logging, notifications). This module owns the
# provider-shape translation only; it deliberately does not
# duplicate any of that Interaction-construction logic.

import base64
import logging
from urllib.parse import unquote

from bs4 import BeautifulSoup

from app.ticketing.schemas.email import EmailRequest, LinkedAttachmentCandidate
from app.ticketing.schemas.mail_integration import GraphAttachmentPayload, IncomingMailPayload
from app.ticketing.utils.constants import MAX_ATTACHMENT_FILES, MAX_ATTACHMENT_SIZE_BYTES
from app.ticketing.utils.validators import sanitize_filename, validate_attachment_type

logger = logging.getLogger(__name__)

GRAPH_FILE_ATTACHMENT_ODATA_TYPE = "#microsoft.graph.fileAttachment"

# Host substrings identifying a OneDrive/SharePoint share link.
# Confirmed live against a real Outlook "Attach as cloud link" send:
# Graph's own attachments collection is empty for these (no
# fileAttachment/referenceAttachment object at all) — the only trace
# is an <a href="https://<tenant>-my.sharepoint.com/...">filename</a>
# anchor Outlook embeds directly in the HTML body (its own
# "_EType_OWALink" card). Matched by href host rather than that CSS
# class, since the class name is Outlook's undocumented internal
# styling hook and not something to depend on across client/version
# combinations — the URL host is the stable, real signal.
CLOUD_LINK_HOST_MARKERS = ("sharepoint.com", "1drv.ms", "onedrive.live.com")


def extract_cloud_link_attachments(html: str) -> list[LinkedAttachmentCandidate]:
    """
    Finds every OneDrive/SharePoint share-link anchor in an inbound
    email's HTML body and returns it as a LinkedAttachmentCandidate
    (filename + url) — the file has no real bytes anywhere Graph
    exposes to us, so this is the only representation possible.

    Unrelated to build_upload_files_from_graph_attachments below: that
    function only ever sees Graph's real `attachments` collection,
    which is empty for this case. This is a second, independent
    extraction over the message body itself.
    """

    candidates: list[LinkedAttachmentCandidate] = []
    seen_urls: set[str] = set()

    for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        href = anchor["href"].strip()

        if not href or href in seen_urls:
            continue
        if not any(marker in href.lower() for marker in CLOUD_LINK_HOST_MARKERS):
            continue

        filename = anchor.get_text(separator=" ").strip()
        if not filename:
            # An icon-only card with no visible link text at all —
            # fall back to the URL's own last path segment rather
            # than dropping the file reference entirely.
            filename = unquote(href.rstrip("/").rsplit("/", 1)[-1]) or "Linked file"

        seen_urls.add(href)
        candidates.append(LinkedAttachmentCandidate(filename=filename[:255], url=href))

        if len(candidates) >= MAX_ATTACHMENT_FILES:
            break

    return candidates


def _extract_header(
    payload: IncomingMailPayload, header_name: str
) -> str | None:
    if not payload.internetMessageHeaders:
        return None

    for header in payload.internetMessageHeaders:
        if header.name.lower() == header_name.lower():
            return header.value

    return None


def _preserve_named_link_hrefs(soup: BeautifulSoup) -> None:
    """
    A plain get_text() keeps only an anchor's visible label, never its
    href — fine for a bare pasted URL (Outlook auto-linkifies it,
    label == href, nothing is lost), but confirmed live as a real bug
    for a *named* link (Outlook's own Insert > Link, with a custom
    "Display as" value like "link"): the actual URL vanishes
    entirely, leaving an inert, unclickable label with no way to
    reach it at all.

    Rewrites each such anchor's contents to "label (href)" in place,
    before get_text() ever runs, so the real URL survives as literal
    text — which the frontend's own linkifyPlainText
    (lib/richText.ts) then turns back into a real clickable link,
    exactly as it already does for a bare pasted URL.

    Skips anchors extract_cloud_link_attachments already handles
    (OneDrive/SharePoint) — those are surfaced separately as a linked
    attachment, not duplicated inline here. Prefers `originalsrc`
    over `href` when present (Outlook's Safe Links rewrites `href` to
    a safelinks.protection.outlook.com tracking redirect and puts the
    real destination in `originalsrc` instead — using `href` here
    would show the ugly tracking URL, not the real one).
    """

    for anchor in soup.find_all("a", href=True):
        href = (anchor.get("originalsrc") or anchor["href"]).strip()

        if not href.lower().startswith(("http://", "https://")):
            continue
        if any(marker in href.lower() for marker in CLOUD_LINK_HOST_MARKERS):
            continue

        label = anchor.get_text(separator=" ").strip()
        if not label:
            anchor.string = href
        elif href not in label:
            anchor.string = f"{label} ({href})"


def _html_to_plain_text(html: str) -> str:
    """
    Graph returns body.contentType="html" for effectively every real-
    world sender (nothing here requests the Prefer:
    outlook.body-content-type="text" header that would make Graph do
    this conversion itself) — this is what keeps EmailRequest.body a
    genuine plain-text field, the contract every other part of this
    system (the schema itself, the form-encoded N8N transport, and the
    frontend's escape-then-linkify rendering in MessageDetailsView.tsx)
    already assumes. html.parser is the stdlib-only backend — no lxml
    dependency needed. get_text() also strips <script>/<style> content
    entirely, not just their tags.
    """

    soup = BeautifulSoup(html, "html.parser")
    _preserve_named_link_hrefs(soup)
    return soup.get_text(separator="\n").strip()


def map_external_email_to_interaction(payload: IncomingMailPayload) -> EmailRequest:
    """
    Maps an external provider's email payload into the internal
    EmailRequest shape. Named to match this integration layer's
    receive-side placeholder — the actual Interaction row is still
    created by the existing, unmodified EmailService.receive_email,
    which this function's output is handed to.
    """

    to_recipient = payload.toRecipients[0].emailAddress

    references_header = _extract_header(payload, "References")
    references = references_header.split() if references_header else []

    is_html = payload.body.contentType == "html"
    # Falls back to the raw HTML on the rare case get_text() yields
    # nothing (e.g. an image-only body with no visible text at all) —
    # EmailRequest.body requires min_length=1, so an empty extraction
    # would otherwise crash the whole message rather than degrade to
    # the pre-fix "shows raw HTML" behavior for just that one message.
    plain_body = (
        (_html_to_plain_text(payload.body.content) or payload.body.content)
        if is_html
        else payload.body.content
    )

    return EmailRequest(
        to_email=to_recipient.address,
        from_email=payload.from_.emailAddress.address,
        from_name=payload.from_.emailAddress.name,
        subject=payload.subject or "(no subject)",
        body=plain_body,
        html_body=payload.body.content if is_html else None,
        linked_attachments=(
            extract_cloud_link_attachments(payload.body.content) if is_html else []
        ),
        cc=[recipient.emailAddress.address for recipient in payload.ccRecipients],
        to_recipients=[recipient.emailAddress.address for recipient in payload.toRecipients],
        message_id=payload.internetMessageId,
        received_at=payload.receivedDateTime,
        in_reply_to=_extract_header(payload, "In-Reply-To"),
        references=references,
        conversation_id=payload.conversationId,
        provider_message_id=payload.id,
    )


class _GraphAttachmentUploadFile:
    """
    A minimal stand-in for fastapi.UploadFile, matching the exact
    interface AttachmentService.validate_and_store_files actually
    reads (`.filename`, `.content_type`, `await .read()`) — same
    convention as the test suite's own FakeUploadFile
    (tests/test_attachment_upload_authorization.py). Building a real
    Starlette UploadFile here would mean depending on that class's
    exact constructor shape for no benefit, since nothing downstream
    needs anything beyond these three members.
    """

    def __init__(self, filename: str, content: bytes, content_type: str | None):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self) -> bytes:
        return self._content


def build_upload_files_from_graph_attachments(
    attachments: list[GraphAttachmentPayload],
) -> list[_GraphAttachmentUploadFile]:
    """
    Maps Graph's raw attachment list (GraphMailProviderClient.
    fetch_message_attachments) into the UploadFile-shaped objects
    AttachmentService.validate_and_store_files already knows how to
    store — the same choke point every other attachment upload path
    (ticket upload, the pre-existing `files` param on
    EmailService.receive_email) already goes through, so this
    function's only job is building that input, never re-implementing
    validation/storage itself.

    Filters out (each logged individually, and counted in the
    `dropped` summary below):
    - `isInline` attachments — typically embedded signature/logo
      images, not something a user is trying to send as a file.
    - anything with an `@odata.type` that's explicitly present but
      not `#microsoft.graph.fileAttachment` (e.g. a forwarded message
      attached as an item, or a reference attachment) — a genuinely
      absent/None `@odata.type` is tolerated rather than treated as
      disqualifying, since Graph only reliably returns that property
      when it's named in the request's own `$select` list.
    - anything with no actual content (contentBytes) — nothing to
      store.

    Defensively pre-validates size/type against AttachmentService's
    own existing limits and drops (logging) anything that would fail
    those checks, rather than letting a single bad attachment raise
    HTTPException mid-EmailService.receive_email and silently fail to
    store the entire email — there's no live HTTP caller for
    Graph-sourced mail to see that exception. Also caps the result at
    MAX_ATTACHMENT_FILES for the same reason (that check would
    otherwise raise for the whole batch instead of just trimming it).
    """

    files: list[_GraphAttachmentUploadFile] = []
    dropped = 0

    for attachment in attachments:
        display_name = attachment.name or "attachment"

        if attachment.isInline:
            logger.warning(
                "Dropping Graph attachment %r — inline attachment", display_name
            )
            dropped += 1
            continue

        if (
            attachment.odata_type is not None
            and attachment.odata_type != GRAPH_FILE_ATTACHMENT_ODATA_TYPE
        ):
            logger.warning(
                "Dropping Graph attachment %r — not a file attachment (@odata.type=%s)",
                display_name,
                attachment.odata_type,
            )
            dropped += 1
            continue

        if not attachment.contentBytes:
            logger.warning(
                "Dropping Graph attachment %r — no contentBytes", display_name
            )
            dropped += 1
            continue

        if len(files) >= MAX_ATTACHMENT_FILES:
            dropped += 1
            continue

        filename = sanitize_filename(attachment.name or "attachment")

        try:
            validate_attachment_type(filename, attachment.contentType)
        except ValueError as exc:
            logger.warning(
                "Dropping Graph attachment %r — %s", filename, exc
            )
            dropped += 1
            continue

        try:
            content = base64.b64decode(attachment.contentBytes)
        except (ValueError, TypeError):
            logger.warning(
                "Dropping Graph attachment %r — undecodable contentBytes", filename
            )
            dropped += 1
            continue

        if len(content) > MAX_ATTACHMENT_SIZE_BYTES:
            logger.warning(
                "Dropping Graph attachment %r — %d bytes exceeds the %d byte limit",
                filename,
                len(content),
                MAX_ATTACHMENT_SIZE_BYTES,
            )
            dropped += 1
            continue

        files.append(
            _GraphAttachmentUploadFile(
                filename=filename,
                content=content,
                content_type=attachment.contentType,
            )
        )

    if dropped:
        logger.warning(
            "Graph attachment mapping: stored %d, dropped %d (unsupported type, "
            "oversized, inline, or non-file attachment)",
            len(files),
            dropped,
        )

    return files

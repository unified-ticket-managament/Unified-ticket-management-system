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

from bs4 import BeautifulSoup

from app.ticketing.schemas.email import EmailRequest
from app.ticketing.schemas.mail_integration import GraphAttachmentPayload, IncomingMailPayload
from app.ticketing.utils.constants import MAX_ATTACHMENT_FILES, MAX_ATTACHMENT_SIZE_BYTES
from app.ticketing.utils.validators import sanitize_filename, validate_attachment_type

logger = logging.getLogger(__name__)

GRAPH_FILE_ATTACHMENT_ODATA_TYPE = "#microsoft.graph.fileAttachment"


def _extract_header(
    payload: IncomingMailPayload, header_name: str
) -> str | None:
    if not payload.internetMessageHeaders:
        return None

    for header in payload.internetMessageHeaders:
        if header.name.lower() == header_name.lower():
            return header.value

    return None


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

    return BeautifulSoup(html, "html.parser").get_text(separator="\n").strip()


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

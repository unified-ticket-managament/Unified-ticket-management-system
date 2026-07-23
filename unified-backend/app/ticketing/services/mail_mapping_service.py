# mail_mapping_service.py
#
# Converts a provider-shaped external email payload (today: a
# realistic Microsoft Graph `message` resource) into this service's
# own EmailRequest — the schema EmailService.receive_email already
# knows how to turn into an Interaction (client resolution,
# threading, audit logging, notifications). This module owns the
# provider-shape translation only; it deliberately does not
# duplicate any of that Interaction-construction logic.

from bs4 import BeautifulSoup

from app.ticketing.schemas.email import EmailRequest
from app.ticketing.schemas.mail_integration import IncomingMailPayload


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
        message_id=payload.internetMessageId,
        received_at=payload.receivedDateTime,
        in_reply_to=_extract_header(payload, "In-Reply-To"),
        references=references,
        conversation_id=payload.conversationId,
        provider_message_id=payload.id,
    )

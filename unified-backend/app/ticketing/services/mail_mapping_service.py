# mail_mapping_service.py
#
# Converts a provider-shaped external email payload (today: a
# realistic Microsoft Graph `message` resource) into this service's
# own EmailRequest — the schema EmailService.receive_email already
# knows how to turn into an Interaction (client resolution,
# threading, audit logging, notifications). This module owns the
# provider-shape translation only; it deliberately does not
# duplicate any of that Interaction-construction logic.

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

    return EmailRequest(
        to_email=to_recipient.address,
        from_email=payload.from_.emailAddress.address,
        from_name=payload.from_.emailAddress.name,
        subject=payload.subject or "(no subject)",
        body=payload.body.content,
        html_body=payload.body.content if is_html else None,
        message_id=payload.internetMessageId,
        received_at=payload.receivedDateTime,
        in_reply_to=_extract_header(payload, "In-Reply-To"),
        references=references,
        conversation_id=payload.conversationId,
    )

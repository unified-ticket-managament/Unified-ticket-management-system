# graph_client.py
#
# The real Microsoft Graph implementation of the MailProviderClient
# seam (mail_provider.py) — send_email() calls Graph's sendMail API
# for a brand-new message, or Graph's reply/replyAll message action
# (via _send_reply) when the envelope carries
# reply_to_provider_message_id, i.e. it's replying to a specific
# existing Graph message rather than composing a new one.
# fetch_message() calls Graph's message-by-id API. Both are used only
# once GraphAuthClient successfully authenticates (see graph_auth.py);
# get_mail_provider_client() is the single place that decides whether
# this class or MockMailProviderClient backs the rest of the app.

import html
import logging
from datetime import datetime

import httpx

from app.core.config import Settings
from app.ticketing.schemas.mail_integration import GraphAttachmentPayload, IncomingMailPayload
from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services.graph_auth import GraphAuthClient
from app.ticketing.services.mail_provider import MailProviderClient, MailProviderSendResult

logger = logging.getLogger(__name__)

# Fields requested on every message fetch — matches IncomingMailPayload's
# own fields one-for-one, plus internetMessageHeaders (only returned when
# explicitly selected) for In-Reply-To/References threading, plus
# hasAttachments so callers can skip the extra attachments call for the
# common no-attachment case.
MESSAGE_SELECT_FIELDS = (
    "id,internetMessageId,subject,from,toRecipients,ccRecipients,body,"
    "conversationId,receivedDateTime,internetMessageHeaders,hasAttachments"
)

class GraphAPIError(Exception):
    """Raised when Graph returns a non-2xx response to a mail send/fetch
    call, after authentication already succeeded."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Graph API error {status_code}: {detail}")


def _build_recipients(addresses: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": address}} for address in addresses]


def _build_graph_attachments(attachments: list) -> list[dict]:
    result = []
    for attachment in attachments:
        item = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": attachment.filename,
            "contentType": attachment.content_type,
            "contentBytes": attachment.content_base64,
        }
        # Only added for a pasted-inline-image attachment (see
        # EnvelopeAttachment.content_id/is_inline) — for every
        # ordinary attachment (is_inline=False, the default, and the
        # only value any attachment has ever had before this feature)
        # this dict stays byte-identical to before: exactly the four
        # keys above, never these two even as null.
        if getattr(attachment, "is_inline", False) and getattr(
            attachment, "content_id", None
        ):
            item["isInline"] = True
            item["contentId"] = attachment.content_id
        result.append(item)
    return result


def _build_send_mail_message(envelope: OutboundEnvelope) -> dict:
    """
    Builds the Graph sendMail `message` object from an envelope.
    Deliberately never sets `internetMessageHeaders` for In-Reply-To/
    References — Graph hard-rejects any header name that doesn't
    start with "x-"/"X-" with a 400 InvalidInternetMessageHeader
    error, failing the entire send. Confirmed live: a real reply
    (which always has `in_reply_to` set) 400'd until this was removed.
    Threading continuity for this platform's own inbound thread-
    matching (EmailService.receive_email) already comes from the
    *stored* envelope's in_reply_to/references, not from anything set
    on the wire — this only ever affected what the recipient's own
    mail client would have seen, and Graph gives no supported way to
    set it via sendMail at all.

    body.contentType is "HTML" only when envelope.body_html is set
    (Outlook-style clipboard paste — see email_envelope.py, the one
    place body_html is populated, already sanitized there). When it's
    None — every send before this field existed, and every plain-text
    send since — this produces the exact same {"contentType": "Text",
    "content": envelope.body} dict as before.
    """

    message: dict = {
        "subject": envelope.subject,
        "body": (
            {"contentType": "HTML", "content": envelope.body_html}
            if envelope.body_html
            else {"contentType": "Text", "content": envelope.body}
        ),
        "toRecipients": _build_recipients(envelope.to_emails or [envelope.to_email]),
    }

    if envelope.cc:
        message["ccRecipients"] = _build_recipients(envelope.cc)
    if envelope.bcc:
        message["bccRecipients"] = _build_recipients(envelope.bcc)
    if envelope.attachments:
        message["attachments"] = _build_graph_attachments(envelope.attachments)

    return message


def _plain_text_to_html_comment(text: str) -> str:
    """
    Graph's reply/replyAll `comment` parameter has no content-type
    option (unlike sendMail's `message.body.contentType`) — Microsoft's
    own docs confirm Graph always composes the resulting reply body as
    HTML from it. A bare `\\n` has no meaning in HTML, so a plain-text
    comment (e.g. a multi-line signature) rendered exactly as typed
    would collapse to one visual line for the recipient. Escape first
    so literal &/</> in the agent's own text can't be misinterpreted
    once composited into HTML, then convert the now-significant
    newlines to <br> so real line breaks survive.
    """

    return html.escape(text).replace("\n", "<br>")


def _build_reply_action_body(envelope: OutboundEnvelope) -> dict:
    """
    Builds the request body for Graph's reply/replyAll message action
    — the `message` sub-object fully overrides recipients/attachments
    rather than relying on the action's own default recipient
    population (reply defaults To the original sender; replyAll
    additionally defaults Cc to the original message's own To+Cc) —
    this platform always resolves the correct To/Cc/Bcc (including
    any agent-picked "To" override) into the envelope itself before
    dispatch, so which action is used only changes which Graph
    endpoint is hit, never who actually receives the mail.

    Graph's reply/replyAll `comment` field has no contentType toggle
    at all (see _plain_text_to_html_comment's own docstring — Graph
    always composes it as HTML) — so when envelope.body_html is
    present, `comment` is that already-sanitized HTML *directly*, not
    run through _plain_text_to_html_comment (which escapes &/</> and
    turns \n into <br>; doing that to already-real HTML would
    double-escape it and break the markup). When body_html is absent —
    every send before this field existed, and every plain-text reply
    since — this produces the exact same
    _plain_text_to_html_comment(envelope.body) call as before.
    """

    message: dict = {
        "toRecipients": _build_recipients([envelope.to_email]),
    }
    if envelope.cc:
        message["ccRecipients"] = _build_recipients(envelope.cc)
    if envelope.bcc:
        message["bccRecipients"] = _build_recipients(envelope.bcc)
    if envelope.attachments:
        message["attachments"] = _build_graph_attachments(envelope.attachments)

    comment = (
        envelope.body_html
        if envelope.body_html
        else _plain_text_to_html_comment(envelope.body)
    )

    return {"comment": comment, "message": message}


class GraphMailProviderClient(MailProviderClient):
    def __init__(self, auth_client: GraphAuthClient, mailbox_address: str, api_base_url: str):
        self._auth_client = auth_client
        self._mailbox_address = mailbox_address
        self._api_base_url = api_base_url.rstrip("/")

    async def _authorized_headers(self) -> dict[str, str]:
        token = await self._auth_client.get_token()
        return {"Authorization": f"Bearer {token}"}

    async def send_email(self, envelope: OutboundEnvelope) -> MailProviderSendResult:
        if envelope.reply_to_provider_message_id:
            return await self._send_reply(envelope)

        message = _build_send_mail_message(envelope)

        url = f"{self._api_base_url}/users/{self._mailbox_address}/sendMail"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers=await self._authorized_headers(),
                json={"message": message, "saveToSentItems": True},
            )

        if response.status_code != 202:
            logger.error(
                "Graph sendMail failed: status=%s to=%s subject=%r body=%s",
                response.status_code,
                envelope.to_email,
                envelope.subject,
                response.text,
            )
            raise GraphAPIError(response.status_code, response.text)

        logger.info(
            "graph provider send: message_id=%s to=%s subject=%r",
            envelope.message_id,
            envelope.to_email,
            envelope.subject,
        )

        # sendMail returns 202 Accepted with no body and no provider-side
        # message id — Graph doesn't hand one back synchronously. Our own
        # envelope.message_id (already stored on the Interaction before
        # this call, see email_envelope.py) remains the only id this
        # platform ever tracks for the outbound message.
        return MailProviderSendResult(
            provider_message_id=envelope.message_id,
            status="SENT",
        )

    async def _send_reply(self, envelope: OutboundEnvelope) -> MailProviderSendResult:
        """
        Sends a reply via Graph's own reply/replyAll message action
        instead of sendMail, so it lands threaded under the original
        conversation in Outlook/Gmail — Graph handles the quoting and
        conversationId continuity itself once pointed at the real
        message being replied to
        (envelope.reply_to_provider_message_id), unlike sendMail,
        which always creates a brand-new, unthreaded message (see
        _build_send_mail_message's own docstring).

        `message` here fully overrides recipients/attachments rather
        than relying on reply/replyAll's own default recipient
        population — this platform already resolved the correct
        To/Cc/Bcc (including any agent-picked "To" override) into the
        envelope before this call, so the action used (reply vs.
        replyAll) only changes which Graph endpoint is hit, not who
        actually receives the mail.
        """

        action = "replyAll" if envelope.reply_all else "reply"
        url = (
            f"{self._api_base_url}/users/{self._mailbox_address}/messages/"
            f"{envelope.reply_to_provider_message_id}/{action}"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers=await self._authorized_headers(),
                json=_build_reply_action_body(envelope),
            )

        if response.status_code != 202:
            logger.error(
                "Graph %s failed: status=%s reply_to=%s to=%s subject=%r body=%s",
                action,
                response.status_code,
                envelope.reply_to_provider_message_id,
                envelope.to_email,
                envelope.subject,
                response.text,
            )
            raise GraphAPIError(response.status_code, response.text)

        logger.info(
            "graph provider %s: reply_to=%s message_id=%s to=%s subject=%r",
            action,
            envelope.reply_to_provider_message_id,
            envelope.message_id,
            envelope.to_email,
            envelope.subject,
        )

        # Same as sendMail — reply/replyAll also return 202 Accepted
        # with no body, so envelope.message_id remains the only id
        # this platform tracks for the outbound message.
        return MailProviderSendResult(
            provider_message_id=envelope.message_id,
            status="SENT",
        )

    async def fetch_message(self, message_id: str) -> IncomingMailPayload:
        url = (
            f"{self._api_base_url}/users/{self._mailbox_address}/messages/{message_id}"
            f"?$select={MESSAGE_SELECT_FIELDS}"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=await self._authorized_headers())

        if response.status_code != 200:
            logger.error(
                "Graph message fetch failed: status=%s message_id=%s body=%s",
                response.status_code,
                message_id,
                response.text,
            )
            raise GraphAPIError(response.status_code, response.text)

        return IncomingMailPayload.model_validate(response.json())

    async def list_new_messages(self, since: datetime) -> list[IncomingMailPayload]:
        """
        Polling alternative to the webhook path — this app asks Graph
        directly rather than waiting for a change notification, so it
        needs no publicly reachable notification URL at all. Reads a
        single page (up to 50 messages, Graph's own default-friendly
        page size here); a mailbox receiving more than that within one
        poll interval would have the remainder picked up on the next
        tick instead (receivedDateTime ordering guarantees nothing is
        skipped, only delayed by one interval) rather than silently
        dropped — not full pagination, a deliberate scope limit for
        the volumes this integration is built for.
        """

        since_literal = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = (
            f"{self._api_base_url}/users/{self._mailbox_address}"
            f"/mailFolders('Inbox')/messages"
            f"?$filter=receivedDateTime gt {since_literal}"
            f"&$orderby=receivedDateTime asc"
            f"&$select={MESSAGE_SELECT_FIELDS}"
            f"&$top=50"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=await self._authorized_headers())

        if response.status_code != 200:
            logger.error(
                "Graph list messages failed: status=%s since=%s body=%s",
                response.status_code,
                since_literal,
                response.text,
            )
            raise GraphAPIError(response.status_code, response.text)

        data = response.json()
        items = data.get("value", [])

        if data.get("@odata.nextLink"):
            logger.warning(
                "Graph list messages: more than %d new message(s) since %s — "
                "the remainder will be picked up on the next poll tick, not "
                "fetched now (no pagination implemented).",
                len(items),
                since_literal,
            )

        return [IncomingMailPayload.model_validate(item) for item in items]

    async def fetch_message_attachments(
        self, message_id: str
    ) -> list[GraphAttachmentPayload]:
        """
        Fetches every attachment on a given message — a second Graph
        call, deliberately only made when the caller already knows
        (via IncomingMailPayload.hasAttachments) there's something to
        fetch. Returns the raw, unfiltered list; deciding which of
        these are real, storable files (as opposed to inline signature
        images) is mail_mapping_service.build_upload_files_from_graph_
        attachments's job, not this transport method's.

        Deliberately no `$select` here: `attachments` is a polymorphic
        collection (fileAttachment/itemAttachment/referenceAttachment)
        and `contentBytes` only exists on the derived fileAttachment
        type — Graph's OData parser 400s ("Could not find a property
        named 'contentBytes' on type 'microsoft.graph.attachment'")
        the instant it's named in a $select here, confirmed live
        against a real message with a real attachment. Omitting
        `$select` returns the full representation instead (including
        `@odata.type` and `contentBytes` for a real fileAttachment),
        which is what this method actually needs.
        """

        url = (
            f"{self._api_base_url}/users/{self._mailbox_address}/messages/{message_id}"
            f"/attachments"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=await self._authorized_headers())

        if response.status_code != 200:
            logger.error(
                "Graph attachments fetch failed: status=%s message_id=%s body=%s",
                response.status_code,
                message_id,
                response.text,
            )
            raise GraphAPIError(response.status_code, response.text)

        data = response.json()
        return [
            GraphAttachmentPayload.model_validate(item) for item in data.get("value", [])
        ]


def build_graph_mail_provider_client(
    settings: Settings,
    auth_client: GraphAuthClient | None,
    mailbox_address: str | None = None,
) -> GraphMailProviderClient | None:
    resolved_mailbox_address = mailbox_address or settings.graph_mailbox_address

    if auth_client is None or not resolved_mailbox_address:
        return None

    return GraphMailProviderClient(
        auth_client=auth_client,
        mailbox_address=resolved_mailbox_address,
        api_base_url=settings.graph_api_base_url,
    )

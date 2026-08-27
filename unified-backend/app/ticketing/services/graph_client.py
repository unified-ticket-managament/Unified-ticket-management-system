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

import base64
import html
import logging
from datetime import datetime

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.ticketing.schemas.mail_integration import GraphAttachmentPayload, IncomingMailPayload
from app.ticketing.schemas.payloads import EnvelopeAttachment, OutboundEnvelope
from app.ticketing.services.graph_auth import GraphAuthClient
from app.ticketing.services.graph_retry import call_with_graph_retry
from app.ticketing.services.mail_provider import MailProviderClient, MailProviderSendResult
from app.ticketing.storage.base import StorageService

logger = logging.getLogger(__name__)

# Graph's documented per-request chunk ceiling for an upload-session
# PUT. Each attachment landing here is already known to be within
# Graph's real ~150MB attachment ceiling (see attachment_service.py's
# GRAPH_INLINE_ATTACHMENT_MAX_BYTES comment) — this only controls how
# many PUT calls one such attachment is split across.
UPLOAD_SESSION_CHUNK_SIZE = 4 * 1024 * 1024

# Fields requested on every message fetch — matches IncomingMailPayload's
# own fields one-for-one, plus internetMessageHeaders (only returned when
# explicitly selected) for In-Reply-To/References threading, plus
# hasAttachments so callers can skip the extra attachments call for the
# common no-attachment case.
MESSAGE_SELECT_FIELDS = (
    "id,internetMessageId,subject,from,toRecipients,ccRecipients,body,"
    "conversationId,receivedDateTime,internetMessageHeaders,hasAttachments"
)

# Bound on how many 50-message pages list_new_messages will follow via
# @odata.nextLink in a single poll tick (~1000 messages) — high enough
# that a mailbox would need to be receiving mail at an extraordinary
# rate to hit it, low enough to guarantee the loop below terminates
# even if Graph ever returned a malformed/looping nextLink chain.
MAX_LIST_MESSAGES_PAGES = 20

class GraphAPIError(Exception):
    """Raised when Graph returns a non-2xx response to a mail send/fetch
    call, after authentication already succeeded.

    `operation` (Phase 2 hardening) is the same short operation name
    already passed to call_with_graph_retry at each raise site
    (e.g. "createDraft", "addAttachment", "sendDraft") — lets a caller
    several layers up (OutboundDispatchError, then
    InteractionService._dispatch_and_record's stored dispatch_error)
    distinguish which Graph call actually failed, instead of collapsing
    every failure into one flat string. Optional/defaulted so every
    pre-existing raise site (and every inbound-fetch one, which this
    class is also used for) stays valid without updating.

    `orphaned_draft_id` is set post-hoc (never via the constructor) by
    _send_via_draft when a failure happens after a real Graph draft was
    already created — see that method's own try/except.
    """

    def __init__(self, status_code: int, detail: str, *, operation: str | None = None):
        self.status_code = status_code
        self.detail = detail
        self.operation = operation
        self.orphaned_draft_id: str | None = None
        super().__init__(f"Graph API error {status_code}: {detail}")


def _build_recipients(addresses: list[str]) -> list[dict]:
    return [{"emailAddress": {"address": address}} for address in addresses]


def _split_envelope_attachments(
    attachments: list[EnvelopeAttachment],
) -> tuple[list[EnvelopeAttachment], list[EnvelopeAttachment]]:
    """
    Splits an envelope's attachments into the ones small enough to
    embed directly (content_base64 set — see
    attachment_service.load_envelope_attachments) and the ones that
    need a real Graph upload session (content_base64 unset,
    storage_key set instead). Every attachment reaching this function
    is one or the other, never neither/both — load_envelope_attachments
    is the only place these are constructed.
    """

    small = [a for a in attachments if a.content_base64 is not None]
    large = [a for a in attachments if a.content_base64 is None]
    return small, large


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
        "toRecipients": _build_recipients(envelope.to_emails or [envelope.to_email]),
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
    def __init__(
        self,
        auth_client: GraphAuthClient,
        mailbox_address: str,
        api_base_url: str,
        storage_service: StorageService | None = None,
    ):
        self._auth_client = auth_client
        self._mailbox_address = mailbox_address
        self._api_base_url = api_base_url.rstrip("/")
        # Only needed for large (over the inline-embed threshold)
        # attachments — see _add_large_attachment. None is fine for
        # every send with no large attachments (the common case) and
        # for every inbound-only use of this client (fetch/list/
        # subscription), none of which ever reach that code path.
        self._storage_service = storage_service

    async def _authorized_headers(self) -> dict[str, str]:
        token = await self._auth_client.get_token()
        return {"Authorization": f"Bearer {token}"}

    async def _force_refresh_token(self) -> None:
        await self._auth_client.get_token(force_refresh=True)

    async def send_email(self, envelope: OutboundEnvelope) -> MailProviderSendResult:
        small_attachments, large_attachments = _split_envelope_attachments(
            envelope.attachments
        )

        if large_attachments:
            # sendMail/reply's inline-JSON attachments can't carry
            # anything this big — build a real draft message instead,
            # attach the small files directly and the large ones via
            # a genuine Graph upload session, then send the draft.
            return await self._send_via_draft(envelope, small_attachments, large_attachments)

        if envelope.reply_to_provider_message_id:
            return await self._send_reply(envelope)

        message = _build_send_mail_message(envelope)

        url = f"{self._api_base_url}/users/{self._mailbox_address}/sendMail"

        async def _attempt() -> httpx.Response:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await client.post(
                    url,
                    headers=await self._authorized_headers(),
                    json={"message": message, "saveToSentItems": True},
                )

        # SEND policy: sendMail returns 202 with no body — a 5xx or a
        # transport failure is genuinely ambiguous about whether Graph
        # already accepted the send, so neither is retried here (see
        # graph_retry.py's module docstring). Only 429 (a definitive
        # synchronous rejection) and 401 (handled via token refresh)
        # are retried.
        response = await call_with_graph_retry(
            _attempt,
            operation="sendMail",
            force_refresh_token=self._force_refresh_token,
            retry_5xx=False,
            retry_on_transport_error=False,
        )

        if response.status_code != 202:
            logger.error(
                "Graph sendMail failed: status=%s to=%s subject=%r body=%s",
                response.status_code,
                envelope.to_email,
                envelope.subject,
                response.text,
            )
            raise GraphAPIError(response.status_code, response.text, operation="sendMail")

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

        async def _attempt() -> httpx.Response:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await client.post(
                    url,
                    headers=await self._authorized_headers(),
                    json=_build_reply_action_body(envelope),
                )

        # SEND policy — same reasoning as send_email's sendMail call:
        # reply/replyAll also returns 202 with no body, so a 5xx/
        # transport failure is never retried, only 429/401.
        response = await call_with_graph_retry(
            _attempt,
            operation=action,
            force_refresh_token=self._force_refresh_token,
            retry_5xx=False,
            retry_on_transport_error=False,
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
            raise GraphAPIError(response.status_code, response.text, operation=action)

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

    # ------------------------------------------------------------
    # Large-attachment path: create a real draft, attach files to
    # it (small ones inline, large ones via a genuine Graph upload
    # session), then send the draft. Used only when send_email finds
    # at least one attachment over the inline-embed threshold — every
    # send with none takes the sendMail/_send_reply fast path above,
    # completely unchanged.
    # ------------------------------------------------------------

    async def _send_via_draft(
        self,
        envelope: OutboundEnvelope,
        small_attachments: list[EnvelopeAttachment],
        large_attachments: list[EnvelopeAttachment],
    ) -> MailProviderSendResult:
        if envelope.reply_to_provider_message_id:
            draft_id = await self._create_reply_draft(envelope)
        else:
            draft_id = await self._create_new_draft(envelope)

        try:
            for attachment in small_attachments:
                await self._add_small_attachment(draft_id, attachment)

            for attachment in large_attachments:
                await self._add_large_attachment(draft_id, attachment)

            await self._send_draft(draft_id)
        except GraphAPIError as exc:
            # Phase 2 hardening: draft_id is only known here, inside
            # this method — a failure past this point means Graph
            # genuinely holds a real, never-sent draft. Annotating it
            # onto the exception (rather than swallowing/re-raising a
            # new one) lets _dispatch_and_record record this
            # distinctly from "never reached Graph at all".
            exc.orphaned_draft_id = draft_id
            raise

        logger.info(
            "graph provider send (draft, %d large attachment(s)): draft_id=%s "
            "message_id=%s to=%s subject=%r",
            len(large_attachments),
            draft_id,
            envelope.message_id,
            envelope.to_email,
            envelope.subject,
        )

        # Unlike sendMail/_send_reply (which return 202 with no body,
        # so envelope.message_id is the only id ever known), this
        # path genuinely creates a real Graph message first — its id
        # is known and worth returning instead of falling back to our
        # own envelope.message_id.
        return MailProviderSendResult(
            provider_message_id=draft_id,
            status="SENT",
        )

    async def _create_new_draft(self, envelope: OutboundEnvelope) -> str:
        """
        Creates a plain (non-reply) draft message — same shape as
        _build_send_mail_message, minus attachments (added afterward,
        individually, by the caller: a not-yet-created message can't
        have its large attachments' upload sessions targeted at it).
        """

        message = _build_send_mail_message(envelope)
        message.pop("attachments", None)

        url = f"{self._api_base_url}/users/{self._mailbox_address}/messages"

        async def _attempt() -> httpx.Response:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await client.post(
                    url,
                    headers=await self._authorized_headers(),
                    json=message,
                )

        response = await call_with_graph_retry(
            _attempt,
            operation="createDraft",
            force_refresh_token=self._force_refresh_token,
        )

        if response.status_code not in (200, 201):
            logger.error(
                "Graph create-draft failed: status=%s to=%s subject=%r body=%s",
                response.status_code,
                envelope.to_email,
                envelope.subject,
                response.text,
            )
            raise GraphAPIError(response.status_code, response.text, operation="createDraft")

        return response.json()["id"]

    async def _create_reply_draft(self, envelope: OutboundEnvelope) -> str:
        """
        Creates a real reply/replyAll draft via Graph's createReply/
        createReplyAll action (as opposed to the direct reply/replyAll
        action _send_reply uses, which sends immediately and returns
        no id) — the draft can then have attachments added to it
        before being sent for real via _send_draft.

        createReply/createReplyAll auto-populate recipients from the
        original message (reply: the original sender; replyAll: the
        original message's own To+Cc too) — this platform always
        resolves the correct To/Cc/Bcc into the envelope itself before
        dispatch (including any agent-picked "To" override), so the
        draft's recipients are explicitly overwritten via a follow-up
        PATCH rather than trusting either action's own defaults, the
        same "envelope is authoritative" contract _build_reply_action_
        body already enforces for the non-draft reply path.
        """

        action = "createReplyAll" if envelope.reply_all else "createReply"
        url = (
            f"{self._api_base_url}/users/{self._mailbox_address}/messages/"
            f"{envelope.reply_to_provider_message_id}/{action}"
        )

        comment = (
            envelope.body_html
            if envelope.body_html
            else _plain_text_to_html_comment(envelope.body)
        )

        async def _attempt() -> httpx.Response:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await client.post(
                    url,
                    headers=await self._authorized_headers(),
                    json={"comment": comment},
                )

        response = await call_with_graph_retry(
            _attempt,
            operation=action,
            force_refresh_token=self._force_refresh_token,
        )

        if response.status_code not in (200, 201):
            logger.error(
                "Graph %s (draft) failed: status=%s reply_to=%s to=%s subject=%r body=%s",
                action,
                response.status_code,
                envelope.reply_to_provider_message_id,
                envelope.to_email,
                envelope.subject,
                response.text,
            )
            raise GraphAPIError(response.status_code, response.text, operation=action)

        draft_id = response.json()["id"]

        patch_url = f"{self._api_base_url}/users/{self._mailbox_address}/messages/{draft_id}"
        patch_body = {
            "toRecipients": _build_recipients(envelope.to_emails or [envelope.to_email]),
            "ccRecipients": _build_recipients(envelope.cc),
            "bccRecipients": _build_recipients(envelope.bcc),
        }

        async def _attempt_patch() -> httpx.Response:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await client.patch(
                    patch_url,
                    headers=await self._authorized_headers(),
                    json=patch_body,
                )

        patch_response = await call_with_graph_retry(
            _attempt_patch,
            operation="draftRecipientPatch",
            force_refresh_token=self._force_refresh_token,
        )

        if patch_response.status_code not in (200, 202):
            logger.error(
                "Graph draft recipient PATCH failed: status=%s draft_id=%s body=%s",
                patch_response.status_code,
                draft_id,
                patch_response.text,
            )
            raise GraphAPIError(
                patch_response.status_code,
                patch_response.text,
                operation="draftRecipientPatch",
            )

        return draft_id

    async def _add_small_attachment(
        self, draft_id: str, attachment: EnvelopeAttachment
    ) -> None:
        item = _build_graph_attachments([attachment])[0]
        url = (
            f"{self._api_base_url}/users/{self._mailbox_address}/messages/"
            f"{draft_id}/attachments"
        )

        async def _attempt() -> httpx.Response:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await client.post(
                    url,
                    headers=await self._authorized_headers(),
                    json=item,
                )

        response = await call_with_graph_retry(
            _attempt,
            operation="addAttachment",
            force_refresh_token=self._force_refresh_token,
        )

        if response.status_code not in (200, 201):
            logger.error(
                "Graph add-attachment failed: status=%s draft_id=%s filename=%r body=%s",
                response.status_code,
                draft_id,
                attachment.filename,
                response.text,
            )
            raise GraphAPIError(response.status_code, response.text, operation="addAttachment")

    async def _add_large_attachment(
        self, draft_id: str, attachment: EnvelopeAttachment
    ) -> None:
        """
        Uploads one large (over the inline-embed threshold) attachment
        to an existing draft via Graph's own chunked upload-session
        flow: createUploadSession, then a series of PUTs to the
        returned uploadUrl in UPLOAD_SESSION_CHUNK_SIZE pieces, each
        carrying a Content-Range header identifying its byte range —
        Graph assembles the final attachment once the last byte
        arrives. Per Microsoft's docs, the uploadUrl is already
        pre-authorized — no Authorization header is sent on the PUTs
        themselves (a bearer token there would be superfluous, not
        required).
        """

        if self._storage_service is None or not attachment.storage_key:
            raise GraphAPIError(
                500,
                f"Cannot send attachment {attachment.filename!r}: no storage "
                "service available to read its content for a Graph upload "
                "session.",
                operation="createUploadSession",
            )

        data = await self._storage_service.download(object_key=attachment.storage_key)
        size = len(data)

        attachment_item: dict = {
            "attachmentType": "file",
            "name": attachment.filename,
            "size": size,
            "contentType": attachment.content_type,
        }
        if attachment.is_inline and attachment.content_id:
            attachment_item["isInline"] = True
            attachment_item["contentId"] = attachment.content_id

        session_url = (
            f"{self._api_base_url}/users/{self._mailbox_address}/messages/"
            f"{draft_id}/attachments/createUploadSession"
        )

        async def _attempt_session() -> httpx.Response:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await client.post(
                    session_url,
                    headers=await self._authorized_headers(),
                    json={"AttachmentItem": attachment_item},
                )

        session_response = await call_with_graph_retry(
            _attempt_session,
            operation="createUploadSession",
            force_refresh_token=self._force_refresh_token,
        )

        if session_response.status_code not in (200, 201):
            logger.error(
                "Graph createUploadSession failed: status=%s draft_id=%s "
                "filename=%r size=%d body=%s",
                session_response.status_code,
                draft_id,
                attachment.filename,
                size,
                session_response.text,
            )
            raise GraphAPIError(
                session_response.status_code,
                session_response.text,
                operation="createUploadSession",
            )

        upload_url = session_response.json()["uploadUrl"]

        async with httpx.AsyncClient(timeout=60.0) as client:
            start = 0
            while start < size:
                end = min(start + UPLOAD_SESSION_CHUNK_SIZE, size) - 1
                chunk = data[start : end + 1]
                chunk_range = f"bytes {start}-{end}/{size}"

                async def _attempt_chunk() -> httpx.Response:
                    return await client.put(
                        upload_url,
                        headers={
                            "Content-Length": str(len(chunk)),
                            "Content-Range": chunk_range,
                        },
                        content=chunk,
                    )

                # Graph's upload-session PUT is idempotent per byte
                # range — resending the same Content-Range is safe, so
                # this retries the one failed chunk in place rather
                # than restarting the whole upload from byte 0. The
                # uploadUrl is pre-authorized (no Authorization header
                # is ever sent here — see this method's own docstring)
                # so a 401 is not expected, but force_refresh_token is
                # still supplied for the wrapper's uniform contract.
                put_response = await call_with_graph_retry(
                    _attempt_chunk,
                    operation="uploadSessionChunk",
                    force_refresh_token=self._force_refresh_token,
                )

                if put_response.status_code not in (200, 201, 202):
                    logger.error(
                        "Graph upload-session chunk failed: status=%s draft_id=%s "
                        "filename=%r range=%d-%d/%d body=%s",
                        put_response.status_code,
                        draft_id,
                        attachment.filename,
                        start,
                        end,
                        size,
                        put_response.text,
                    )
                    raise GraphAPIError(
                        put_response.status_code,
                        put_response.text,
                        operation="uploadSessionChunk",
                    )

                start = end + 1

    async def _send_draft(self, draft_id: str) -> None:
        url = (
            f"{self._api_base_url}/users/{self._mailbox_address}/messages/"
            f"{draft_id}/send"
        )

        async def _attempt() -> httpx.Response:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await client.post(url, headers=await self._authorized_headers())

        # SEND policy — sending the draft is the actual dispatch of
        # the customer email (same reasoning as sendMail/_send_reply).
        response = await call_with_graph_retry(
            _attempt,
            operation="sendDraft",
            force_refresh_token=self._force_refresh_token,
            retry_5xx=False,
            retry_on_transport_error=False,
        )

        if response.status_code != 202:
            logger.error(
                "Graph draft send failed: status=%s draft_id=%s body=%s",
                response.status_code,
                draft_id,
                response.text,
            )
            raise GraphAPIError(response.status_code, response.text, operation="sendDraft")

    async def fetch_message(self, message_id: str) -> IncomingMailPayload:
        url = (
            f"{self._api_base_url}/users/{self._mailbox_address}/messages/{message_id}"
            f"?$select={MESSAGE_SELECT_FIELDS}"
        )

        async def _attempt() -> httpx.Response:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await client.get(url, headers=await self._authorized_headers())

        response = await call_with_graph_retry(
            _attempt,
            operation="fetchMessage",
            force_refresh_token=self._force_refresh_token,
        )

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
        needs no publicly reachable notification URL at all. Reads
        pages of up to 50 messages (Graph's own default-friendly page
        size), following `@odata.nextLink` until Graph reports no more
        pages or MAX_LIST_MESSAGES_PAGES is reached — the caller
        (`graph_mail_poller._poll_one_mailbox`) advances this
        mailbox's checkpoint all the way to the tick's own start time
        once every returned message is stored, which is only correct
        if this method actually returned everything since `since`; a
        single-page read used to silently violate that contract
        whenever a mailbox received more than 50 new messages within
        one poll interval; anything beyond position 50 would never be
        fetched again once the checkpoint advanced past it.
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

        items: list[dict] = []
        pages_fetched = 0

        while url is not None:

            async def _attempt(url: str = url) -> httpx.Response:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    return await client.get(url, headers=await self._authorized_headers())

            response = await call_with_graph_retry(
                _attempt,
                operation="listNewMessages",
                force_refresh_token=self._force_refresh_token,
            )

            if response.status_code != 200:
                logger.error(
                    "Graph list messages failed: status=%s since=%s body=%s",
                    response.status_code,
                    since_literal,
                    response.text,
                )
                raise GraphAPIError(response.status_code, response.text)

            data = response.json()
            items.extend(data.get("value", []))
            pages_fetched += 1

            url = data.get("@odata.nextLink")
            if url and pages_fetched >= MAX_LIST_MESSAGES_PAGES:
                logger.error(
                    "Graph list messages: hit the %d-page cap since %s with "
                    "more pages still remaining — remainder deferred to the "
                    "next poll tick.",
                    MAX_LIST_MESSAGES_PAGES,
                    since_literal,
                )
                url = None

        messages: list[IncomingMailPayload] = []

        for item in items:
            try:
                messages.append(IncomingMailPayload.model_validate(item))
            except ValidationError:
                # A single message Graph itself is happy to return can
                # still fail this schema (e.g. a legitimately empty
                # toRecipients on a Bcc-only delivery, or a malformed
                # sender address on some legacy/relay-sent mail) —
                # this used to raise out of the list comprehension,
                # failing the *entire* batch. Caught here at the
                # poller's own blanket `except Exception` before any
                # message was even looked at, which left the
                # mailbox's checkpoint un-advanced and re-fetched this
                # exact poison message, and every legitimate message
                # behind it, forever on every subsequent tick — a
                # permanent, silent inbound outage for that mailbox.
                # Skipping just this one item lets every other message
                # in the batch (and every later tick) proceed
                # normally; this one is logged loudly (not persisted
                # to inbound_mail_failures — this layer has no DB
                # access — so it's visible in logs/alerting but not
                # yet in the Inbound Failures list; a real, separate
                # gap, not silently fixed here).
                logger.error(
                    "Graph poll: message failed schema validation and was "
                    "skipped (graph_id=%s internetMessageId=%s subject=%r)",
                    item.get("id"),
                    item.get("internetMessageId"),
                    item.get("subject"),
                    exc_info=True,
                )

        return messages

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

        async def _attempt() -> httpx.Response:
            async with httpx.AsyncClient(timeout=30.0) as client:
                return await client.get(url, headers=await self._authorized_headers())

        response = await call_with_graph_retry(
            _attempt,
            operation="fetchMessageAttachments",
            force_refresh_token=self._force_refresh_token,
        )

        if response.status_code != 200:
            logger.error(
                "Graph attachments fetch failed: status=%s message_id=%s body=%s",
                response.status_code,
                message_id,
                response.text,
            )
            raise GraphAPIError(response.status_code, response.text)

        data = response.json()
        raw_items = data.get("value", [])
        await self._resolve_item_attachments(message_id, raw_items)

        attachments: list[GraphAttachmentPayload] = []

        for item in raw_items:
            try:
                attachments.append(GraphAttachmentPayload.model_validate(item))
            except ValidationError:
                # Mirrors the same fix applied to list_new_messages
                # above: one malformed attachment (e.g. an explicit
                # `"name": null` from a relay/forwarder, which fails
                # GraphAttachmentPayload's non-nullable `name` field)
                # used to raise out of this list comprehension,
                # failing every attachment on the message — not just
                # the offending one. The caller's own blanket
                # `except Exception` (mail_integration.py /
                # graph_mail_poller.py) then stored the whole email
                # with zero attachments. Skipping just this one item
                # lets every well-formed attachment on the same
                # message survive.
                logger.error(
                    "Graph attachments fetch: one attachment on message %s "
                    "failed schema validation and was skipped (id=%s name=%r)",
                    message_id,
                    item.get("id"),
                    item.get("name"),
                    exc_info=True,
                )

        return attachments

    async def _resolve_item_attachments(
        self, message_id: str, raw_items: list[dict]
    ) -> None:
        """
        Preserves an Outlook itemAttachment (a forwarded/nested email,
        e.g. "Attach as email") as a downloadable .eml instead of
        silently dropping it — mail_mapping_service.
        build_upload_files_from_graph_attachments drops every
        non-fileAttachment item today since only fileAttachment
        carries contentBytes. Graph's `.../attachments/{id}/$value`
        returns an itemAttachment's raw RFC 5322 (MIME) bytes directly
        (not JSON) — fetching that here and synthesizing a
        fileAttachment-shaped `contentBytes`/`contentType`/`name` onto
        the raw dict lets the existing mapping/validation pipeline
        carry it through unchanged, as an opaque message/rfc822 file.
        No TNEF decoding, no nested-message rendering, no new storage
        mechanism — purely additive to the existing drop/filter logic.

        Best-effort: any failure fetching one nested message is
        logged and left alone (no contentBytes synthesized), so it's
        dropped exactly as it is today — one bad nested-message fetch
        never fails the whole inbound email.
        """

        for item in raw_items:
            if item.get("@odata.type") != "#microsoft.graph.itemAttachment":
                continue

            attachment_id = item.get("id")
            if not attachment_id:
                continue

            value_url = (
                f"{self._api_base_url}/users/{self._mailbox_address}/messages/"
                f"{message_id}/attachments/{attachment_id}/$value"
            )

            async def _attempt() -> httpx.Response:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    return await client.get(
                        value_url, headers=await self._authorized_headers()
                    )

            try:
                response = await call_with_graph_retry(
                    _attempt,
                    operation="fetchItemAttachmentValue",
                    force_refresh_token=self._force_refresh_token,
                )
            except Exception:
                logger.warning(
                    "Graph fetch of itemAttachment %r ($value) on message %s "
                    "failed — leaving it unresolved (dropped downstream, "
                    "same as today).",
                    item.get("name"),
                    message_id,
                    exc_info=True,
                )
                continue

            if response.status_code != 200:
                logger.warning(
                    "Could not resolve nested-message itemAttachment %r on "
                    "message %s — leaving it unresolved (dropped downstream, "
                    "same as today).",
                    item.get("name"),
                    message_id,
                )
                continue

            name = item.get("name") or "forwarded-message"
            if not name.lower().endswith(".eml"):
                name = f"{name}.eml"

            item["name"] = name
            item["contentType"] = "message/rfc822"
            item["contentBytes"] = base64.b64encode(response.content).decode("ascii")


def build_graph_mail_provider_client(
    settings: Settings,
    auth_client: GraphAuthClient | None,
    mailbox_address: str | None = None,
    storage_service: StorageService | None = None,
) -> GraphMailProviderClient | None:
    resolved_mailbox_address = mailbox_address or settings.graph_mailbox_address

    if auth_client is None or not resolved_mailbox_address:
        return None

    return GraphMailProviderClient(
        auth_client=auth_client,
        mailbox_address=resolved_mailbox_address,
        api_base_url=settings.graph_api_base_url,
        storage_service=storage_service,
    )

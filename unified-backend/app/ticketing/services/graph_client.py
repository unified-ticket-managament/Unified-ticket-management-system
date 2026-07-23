# graph_client.py
#
# The real Microsoft Graph implementation of the MailProviderClient
# seam (mail_provider.py) — send_email() calls Graph's sendMail API,
# fetch_message() calls Graph's message-by-id API. Both are used only
# once GraphAuthClient successfully authenticates (see graph_auth.py);
# get_mail_provider_client() is the single place that decides whether
# this class or MockMailProviderClient backs the rest of the app.

import logging
from datetime import datetime

import httpx

from app.core.config import Settings
from app.ticketing.schemas.mail_integration import IncomingMailPayload
from app.ticketing.schemas.payloads import OutboundEnvelope
from app.ticketing.services.graph_auth import GraphAuthClient
from app.ticketing.services.mail_provider import MailProviderClient, MailProviderSendResult

logger = logging.getLogger(__name__)

# Fields requested on every message fetch — matches IncomingMailPayload's
# own fields one-for-one, plus internetMessageHeaders (only returned when
# explicitly selected) for In-Reply-To/References threading.
MESSAGE_SELECT_FIELDS = (
    "id,internetMessageId,subject,from,toRecipients,ccRecipients,body,"
    "conversationId,receivedDateTime,internetMessageHeaders"
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
    """

    message: dict = {
        "subject": envelope.subject,
        "body": {"contentType": "Text", "content": envelope.body},
        "toRecipients": _build_recipients([envelope.to_email]),
    }

    if envelope.cc:
        message["ccRecipients"] = _build_recipients(envelope.cc)
    if envelope.bcc:
        message["bccRecipients"] = _build_recipients(envelope.bcc)

    return message


class GraphMailProviderClient(MailProviderClient):
    def __init__(self, auth_client: GraphAuthClient, mailbox_address: str, api_base_url: str):
        self._auth_client = auth_client
        self._mailbox_address = mailbox_address
        self._api_base_url = api_base_url.rstrip("/")

    async def _authorized_headers(self) -> dict[str, str]:
        token = await self._auth_client.get_token()
        return {"Authorization": f"Bearer {token}"}

    async def send_email(self, envelope: OutboundEnvelope) -> MailProviderSendResult:
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


def build_graph_mail_provider_client(
    settings: Settings, auth_client: GraphAuthClient | None
) -> GraphMailProviderClient | None:
    if auth_client is None or not settings.graph_mailbox_address:
        return None

    return GraphMailProviderClient(
        auth_client=auth_client,
        mailbox_address=settings.graph_mailbox_address,
        api_base_url=settings.graph_api_base_url,
    )

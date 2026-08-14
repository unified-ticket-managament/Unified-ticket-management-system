# email_sender.py

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmailSender:
    """
    The seam real outbound notification email plugs into — deliberately
    narrower than OutboundDispatcher (the client-facing reply-email
    seam in app/ticketing/services/outbound_dispatcher.py): this is for
    a plain subject+body message to one internal user's own inbox
    (SLA breach escalations today), not a threaded client conversation
    with envelope headers/message-id tracking. No provider is assumed
    at this layer — get_email_sender() below picks the concrete
    implementation based on config, so callers never construct one
    directly and never need to change if the transport does.
    """

    async def send(
        self, *, to_email: str, subject: str, body: str, html_body: str | None = None
    ) -> bool:
        raise NotImplementedError


class LoggingEmailSender(EmailSender):
    """
    Used whenever no real transport is configured (smtp_host unset) —
    logs what would have been sent instead of silently no-op-ing or
    raising, the same convention OutboundDispatcher's own no-op already
    established for the client-reply seam. This is the default until
    real SMTP credentials are supplied in .env.
    """

    async def send(
        self, *, to_email: str, subject: str, body: str, html_body: str | None = None
    ) -> bool:
        logger.info(
            "EMAIL (no SMTP transport configured — see smtp_host in Settings) "
            "to=%s subject=%r html=%s",
            to_email,
            subject,
            html_body is not None,
        )
        return False


class GraphEmailSender(EmailSender):
    """
    Real transport via Microsoft Graph's sendMail API, using the same
    app-only (client-credentials) Graph identity already configured for
    client-facing mail (app/ticketing/services/graph_auth.py /
    graph_client.py) — reused here rather than duplicated: this class
    is handed an already-built GraphAuthClient (get_email_sender()
    obtains it via build_graph_auth_client(), the same cached MSAL
    singleton the client-mail feature uses, so token acquisition/reuse
    behavior is identical).

    Deliberately does not go through GraphMailProviderClient/
    OutboundEnvelope (graph_client.py) — that abstraction is built
    around ticket-reply threading and attachments, always sends
    contentType "Text", and raising GraphAPIError on failure. A
    notification email is a simpler shape (no threading, optionally
    HTML) and needs the same never-raise/return-bool contract every
    other EmailSender implementation here already has, so this builds
    its own minimal sendMail request instead of forcing that fit.
    """

    def __init__(self, *, auth_client, mailbox_address: str, api_base_url: str):
        self._auth_client = auth_client
        self._mailbox_address = mailbox_address
        self._api_base_url = api_base_url.rstrip("/")

    async def send(
        self, *, to_email: str, subject: str, body: str, html_body: str | None = None
    ) -> bool:
        content_type = "HTML" if html_body is not None else "Text"
        content = html_body if html_body is not None else body

        message = {
            "subject": subject,
            "body": {"contentType": content_type, "content": content},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        }

        url = f"{self._api_base_url}/users/{self._mailbox_address}/sendMail"

        try:
            token = await self._auth_client.get_token()
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    json={"message": message, "saveToSentItems": True},
                )

            if response.status_code != 202:
                logger.error(
                    "Graph sendMail failed for notification email: status=%s to=%s "
                    "subject=%r body=%s",
                    response.status_code,
                    to_email,
                    subject,
                    response.text,
                )
                return False

            return True
        except Exception:
            # Never let a notification-email failure propagate into the
            # business action it's attached to — same convention
            # SMTPEmailSender.send already established below.
            logger.exception(
                "Failed to send notification email via Graph to=%s subject=%r",
                to_email,
                subject,
            )
            return False


class SMTPEmailSender(EmailSender):
    """
    Real transport via any standard SMTP server. smtplib is blocking,
    so the actual send runs in a worker thread (asyncio.to_thread)
    rather than blocking the event loop other requests are sharing.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        from_email: str,
        use_tls: bool,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._from_email = from_email
        self._use_tls = use_tls

    async def send(
        self, *, to_email: str, subject: str, body: str, html_body: str | None = None
    ) -> bool:
        try:
            await asyncio.to_thread(self._send_sync, to_email, subject, body, html_body)
            return True
        except Exception:
            # Never let a notification-email failure propagate into the
            # business action it's attached to (an SLA breach tick, a
            # ticket completion) — same "SLA bookkeeping never blocks
            # triage" convention this feature already follows elsewhere.
            logger.exception(
                "Failed to send notification email to=%s subject=%r",
                to_email,
                subject,
            )
            return False

    def _send_sync(
        self, to_email: str, subject: str, body: str, html_body: str | None
    ) -> None:
        # multipart/alternative (not the bare MIMEMultipart() this used
        # to construct) so a client that renders HTML shows html_body
        # and one that doesn't falls back to the plain-text body — both
        # parts describe the same content, never two different messages.
        message = MIMEMultipart("alternative")
        message["From"] = self._from_email
        message["To"] = to_email
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))
        if html_body is not None:
            message.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(self._host, self._port, timeout=10) as server:
            if self._use_tls:
                server.starttls()
            if self._username and self._password:
                server.login(self._username, self._password)
            server.sendmail(self._from_email, [to_email], message.as_string())


def get_email_sender() -> EmailSender:
    """
    Constructed fresh per call (cheap — no connection opens until
    .send() actually runs) rather than cached, so a test can monkeypatch
    this function or flip settings without needing to clear a cache,
    matching how get_settings() itself is the only thing actually
    memoized in this codebase.

    Prefers Microsoft Graph (the ticketing@... mailbox already
    configured for client-facing mail) whenever graph_tenant_id/
    graph_client_id/graph_client_secret/graph_mailbox_address are all
    set — the same identity, reused rather than a second email
    service. Falls back to SMTP if only smtp_host is configured, then
    to logging-only if neither transport is configured. Imports
    build_graph_auth_client lazily (function-local, not module-level)
    to keep app/core from depending on app/ticketing/services at
    import time — the same deferred-import precedent
    app/ticketing/services/mail_provider.py's own
    get_mail_provider_client() already sets, just in the opposite
    direction.
    """

    settings = get_settings()

    if (
        settings.graph_tenant_id
        and settings.graph_client_id
        and settings.graph_client_secret
        and settings.graph_mailbox_address
    ):
        from app.ticketing.services.graph_auth import build_graph_auth_client

        auth_client = build_graph_auth_client(settings)
        if auth_client is not None:
            return GraphEmailSender(
                auth_client=auth_client,
                mailbox_address=settings.graph_mailbox_address,
                api_base_url=settings.graph_api_base_url,
            )

    if not settings.smtp_host:
        return LoggingEmailSender()

    return SMTPEmailSender(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        from_email=settings.smtp_from_email or "no-reply@example.com",
        use_tls=settings.smtp_use_tls,
    )

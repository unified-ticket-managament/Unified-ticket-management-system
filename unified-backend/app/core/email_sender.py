# email_sender.py

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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

    async def send(self, *, to_email: str, subject: str, body: str) -> bool:
        raise NotImplementedError


class LoggingEmailSender(EmailSender):
    """
    Used whenever no real transport is configured (smtp_host unset) —
    logs what would have been sent instead of silently no-op-ing or
    raising, the same convention OutboundDispatcher's own no-op already
    established for the client-reply seam. This is the default until
    real SMTP credentials are supplied in .env.
    """

    async def send(self, *, to_email: str, subject: str, body: str) -> bool:
        logger.info(
            "EMAIL (no SMTP transport configured — see smtp_host in Settings) "
            "to=%s subject=%r",
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

    async def send(self, *, to_email: str, subject: str, body: str) -> bool:
        try:
            await asyncio.to_thread(self._send_sync, to_email, subject, body)
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

    def _send_sync(self, to_email: str, subject: str, body: str) -> None:
        message = MIMEMultipart()
        message["From"] = self._from_email
        message["To"] = to_email
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))

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
    """

    settings = get_settings()

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

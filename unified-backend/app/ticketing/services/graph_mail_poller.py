# graph_mail_poller.py
#
# Polling-based inbound mail intake — an alternative to the webhook/
# subscription path (graph_subscription_service.py, POST /api/mail/
# incoming) for whenever a public HTTPS notification URL isn't
# available (the common local-dev case: no ngrok/tunnel set up yet).
# This app initiates the check itself on a timer (see
# app/core/graph_mail_poll_scheduler.py) rather than waiting for Graph
# to call back — no GRAPH_WEBHOOK_CLIENT_STATE/
# GRAPH_WEBHOOK_NOTIFICATION_URL needed, only the same four identity
# settings send_email/fetch_message already require.
#
# Both transports converge on the same map_external_email_to_interaction
# + EmailService.receive_email pipeline and the same message_id
# duplicate-detection safety net (see email_service.py) — so running
# polling and the webhook path at the same time, once a public URL
# eventually exists too, is safe: whichever transport sees a message
# first stores it, and the other's later delivery of the same message
# is simply rejected as already-processed, not double-counted.

import logging
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.database.session import AsyncSessionLocal
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.attachment_service import AttachmentService
from app.ticketing.services.email_service import EmailService
from app.ticketing.services.graph_client import GraphAPIError
from app.ticketing.services.mail_mapping_service import (
    body_references_inline_attachment,
    build_upload_files_from_graph_attachments,
    map_external_email_to_interaction,
)
from app.ticketing.services.mail_provider import get_mail_provider_client
from app.ticketing.services.rule_engine_service import build_rule_engine_service
from app.ticketing.services.sla_service import build_sla_service
from app.ticketing.storage import get_storage_service

logger = logging.getLogger(__name__)

# How far back this process looks on its very first poll tick — avoids
# replaying a mailbox's entire history on cold start while still
# catching anything that arrived shortly before the process started.
INITIAL_LOOKBACK_MINUTES = 15


class _PollState:
    """Module-level, in-process only — deliberately not persisted, same
    tradeoff as graph_subscription_service._SubscriptionState. A fresh
    process re-checks the last INITIAL_LOOKBACK_MINUTES for every
    mailbox rather than resuming a previous process's exact
    checkpoints; the message_id dedupe check in
    EmailService.receive_email makes re-seeing an already-stored
    message from that overlap window harmless.

    Keyed per mailbox address (lowercased) rather than a single
    scalar — the legacy shared mailbox and every client-specific
    mailbox each advance independently, and one mailbox's checkpoint
    never affects another's."""

    checkpoints: dict[str, datetime] = {}


_state = _PollState()


def _build_email_service(db) -> EmailService:
    """
    Mirrors api/email.py's and api/mail_integration.py's own identically-
    named local builder — kept local here too rather than imported,
    since both of those are module-private, following the existing
    convention rather than introducing a new shared import for it.
    """

    interaction_repository = InteractionRepository(db)
    client_repository = ClientRepository(db)
    attachment_repository = AttachmentRepository(db)
    user_repository = UserRepository(db)

    attachment_service = AttachmentService(
        attachment_repository=attachment_repository,
        interaction_repository=interaction_repository,
        ticket_repository=TicketRepository(db),
        storage_service=get_storage_service(),
    )

    notification_service = NotificationService(NotificationRepository(db))

    return EmailService(
        interaction_repository=interaction_repository,
        client_repository=client_repository,
        attachment_service=attachment_service,
        user_repository=user_repository,
        ticket_repository=TicketRepository(db),
        notification_service=notification_service,
        sla_service=build_sla_service(db, notification_service=notification_service),
        rule_engine_service=build_rule_engine_service(db),
    )


def is_ready_to_poll(settings: Settings) -> bool:
    """
    True once the four identity/mailbox settings send_email and
    fetch_message already require are all configured — deliberately
    NOT gated on GRAPH_WEBHOOK_CLIENT_STATE/
    GRAPH_WEBHOOK_NOTIFICATION_URL (graph_subscription_service's own
    gate), since polling needs neither: there's no webhook to
    validate or forge here, only an authenticated call this app itself
    initiates.
    """

    return bool(
        settings.graph_tenant_id
        and settings.graph_client_id
        and settings.graph_client_secret
        and settings.graph_mailbox_address
    )


async def _resolve_mailboxes_to_poll(settings: Settings) -> list[str]:
    """
    The full set of mailboxes this tick attempts: the one configured
    shared mailbox plus every active client's own inbox_email (see
    ClientRepository.list_active_inbox_emails) — deduped/lowercased,
    so a client whose inbox_email happens to equal the shared mailbox
    doesn't get polled twice. Not every address returned here is
    necessarily a real, Graph-accessible mailbox yet (some may still
    be awaiting Azure app-access approval, or be a legacy non-Graph
    address) — that's discovered per-mailbox in _poll_one_mailbox,
    not filtered out here.
    """

    mailboxes = {settings.graph_mailbox_address.strip().lower()}

    async with AsyncSessionLocal() as db:
        client_inbox_emails = await ClientRepository(db).list_active_inbox_emails()

    mailboxes.update(
        email.strip().lower() for email in client_inbox_emails if email
    )

    return sorted(mailboxes)


async def poll_new_messages(settings: Settings) -> None:
    """
    Idempotent, safe to call on every scheduler tick: no-ops whenever
    Graph isn't fully configured for send/fetch, otherwise polls every
    mailbox in _resolve_mailboxes_to_poll independently. One mailbox's
    failure (including one that isn't Graph-accessible yet — see
    _poll_one_mailbox) never prevents another mailbox's tick from
    running.
    """

    if not is_ready_to_poll(settings):
        logger.debug(
            "Graph mail polling skipped — tenant/client/secret/mailbox not "
            "fully configured yet."
        )
        return

    tick_started_at = datetime.now(timezone.utc)
    mailboxes = await _resolve_mailboxes_to_poll(settings)

    for mailbox_address in mailboxes:
        try:
            await _poll_one_mailbox(settings, mailbox_address, tick_started_at)
        except Exception:
            # Anything _poll_one_mailbox itself didn't already catch
            # (e.g. a failure resolving the mail provider client) —
            # never let one mailbox's crash stop the rest of this
            # tick's loop.
            logger.exception(
                "Graph mail polling: mailbox %s tick failed entirely",
                mailbox_address,
            )


async def _poll_one_mailbox(
    settings: Settings, mailbox_address: str, tick_started_at: datetime
) -> None:
    """
    One mailbox's full poll-and-process cycle for this tick. A Graph
    error here (most commonly 403/404 — this mailbox not yet granted
    Graph app access, an expected and ongoing condition for a client
    mailbox awaiting Azure authorization) is logged at warning, not
    exception, and simply leaves this mailbox's checkpoint
    un-advanced for a retry next tick — no backoff/skip-list, since
    there's nowhere schema-free to remember "this one is known-bad"
    across ticks, and the volumes here don't warrant one.
    """

    mail_provider_client = get_mail_provider_client(settings, mailbox_address=mailbox_address)

    if mail_provider_client.__class__.__name__ != "GraphMailProviderClient":
        # Unreachable given is_ready_to_poll() above, but never trust
        # that invariant blindly against a future edit to either
        # function independently — same defensive shape
        # graph_subscription_service.ensure_subscription uses.
        logger.debug("Graph mail polling skipped — provider client is not Graph-backed.")
        return

    since = _state.checkpoints.get(mailbox_address) or (
        datetime.now(timezone.utc) - timedelta(minutes=INITIAL_LOOKBACK_MINUTES)
    )

    try:
        messages = await mail_provider_client.list_new_messages(since=since)
    except GraphAPIError as exc:
        logger.warning(
            "Graph mail polling: mailbox %s not reachable (status=%s) — will "
            "retry next tick",
            mailbox_address,
            exc.status_code,
        )
        return
    except Exception:
        logger.exception(
            "Graph mail polling: failed to list new messages for mailbox %s",
            mailbox_address,
        )
        return

    processed = 0

    for payload in messages:
        email_request = map_external_email_to_interaction(
            payload, landed_mailbox=mailbox_address
        )

        files = None
        if payload.id and (
            payload.hasAttachments or body_references_inline_attachment(payload.body.content)
        ):
            try:
                attachments = await mail_provider_client.fetch_message_attachments(payload.id)
                files = build_upload_files_from_graph_attachments(attachments)
            except Exception:
                logger.exception(
                    "Graph poll: failed to fetch attachments for message %s — "
                    "storing without them",
                    payload.internetMessageId,
                )

        async with AsyncSessionLocal() as db:
            try:
                service = _build_email_service(db)
                await service.receive_email(email_request, files=files)
                await db.commit()
                processed += 1
            except ValueError as exc:
                # "Email already processed." (overlap with a prior poll
                # or the webhook path already having caught it) and
                # "Unknown inbox address." are expected, non-exceptional
                # outcomes here — log at info, not exception.
                await db.rollback()
                logger.info(
                    "Graph poll: message %s not stored: %s",
                    payload.internetMessageId,
                    exc,
                )
            except Exception:
                await db.rollback()
                logger.exception(
                    "Graph poll: processing failed for message %s",
                    payload.internetMessageId,
                )

    # Advances even on a tick that processed nothing (or failed
    # partway through some messages) — this is a checkpoint of "we
    # asked Graph as of this time," not "we successfully stored
    # everything as of this time." A message that failed to process
    # is not retried by a later tick; it would need to be re-sent or
    # handled manually. Acceptable for this integration's current
    # scope — see EMAIL_INTEGRATION_CHECKLIST.md's existing note on
    # retry/dead-letter handling being unbuilt.
    _state.checkpoints[mailbox_address] = tick_started_at

    if messages:
        logger.info(
            "Graph mail polling: mailbox %s saw %d message(s), stored %d",
            mailbox_address,
            len(messages),
            processed,
        )

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
from app.rbac.repositories.category_repository import CategoryRepository
from app.rbac.repositories.reporting_manager_repository import (
    ReportingManagerRepository,
)
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.inbound_mail_failure_repository import (
    InboundMailFailureRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mailbox_poll_state_repository import (
    MailboxPollStateRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.attachment_service import AttachmentService
from app.ticketing.services.email_service import EmailService
from app.ticketing.services.graph_client import GraphAPIError
from app.ticketing.services.mail_integrity import is_duplicate_message_id_violation
from app.ticketing.services.mail_mapping_service import (
    body_references_inline_attachment,
    build_upload_files_from_graph_attachments,
    map_external_email_to_interaction,
)
from app.ticketing.services.mail_ops_alerts import (
    notify_mailbox_poll_stalled,
    notify_unmatched_inbox_email,
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

# How many consecutive poll ticks a single message is allowed to keep
# failing (a genuine, unexpected exception — not the terminal "already
# processed"/"unknown inbox address" ValueErrors, which are never
# retried) before it's dead-lettered: logged distinctly and allowed to
# stop holding back this mailbox's checkpoint. Bounded specifically so
# one permanently-broken message (a bug this exact retry can't fix)
# can't block every other message in the same and later ticks forever.
MAX_MESSAGE_RETRY_ATTEMPTS = 3


class _PollState:
    """Module-level, in-process cache of each mailbox's checkpoint —
    seeded from the persisted `mailbox_poll_state` table
    (MailboxPollStateRepository) on this process's first tick after a
    (re)start (see _seed_checkpoints_from_persisted_state below), so a
    restart no longer means every mailbox falls back all the way to
    INITIAL_LOOKBACK_MINUTES. That fallback still applies to a mailbox
    with no persisted row at all (a genuinely new one). Either way,
    the message_id dedupe check in EmailService.receive_email makes
    re-seeing an already-stored message from an overlap window
    harmless.

    Keyed per mailbox address (lowercased) rather than a single
    scalar — the legacy shared mailbox and every client-specific
    mailbox each advance independently, and one mailbox's checkpoint
    never affects another's.

    `failure_counts` tracks, per mailbox, how many consecutive ticks
    each still-unresolved message (keyed by its own internetMessageId)
    has failed with a genuine exception — this is what makes
    _poll_one_mailbox hold the checkpoint back at exactly that
    message's arrival time instead of unconditionally advancing past
    it (the previously-accepted, now-fixed gap: a message that failed
    once was never retried by any later tick)."""

    checkpoints: dict[str, datetime] = {}
    failure_counts: dict[str, dict[str, int]] = {}
    # True once this process has attempted the one-time persisted-
    # checkpoint seed (successfully or not) — attempted at most once
    # per process, not once per tick, since after the first tick
    # checkpoints are advanced (and persisted) directly and re-seeding
    # from the DB would just be a redundant read.
    checkpoints_seeded: bool = False


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
        category_repository=CategoryRepository(db),
        reporting_manager_repository=ReportingManagerRepository(db),
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
    shared mailbox, every active client's own inbox_email (see
    ClientRepository.list_active_inbox_emails), and every category's
    own inbox_email (CategoryRepository.list_active_inbox_emails) —
    deduped/lowercased, so an address configured on more than one of
    these doesn't get polled twice. Not every address returned here is
    necessarily a real, Graph-accessible mailbox yet (some may still
    be awaiting Azure app-access approval, or be a legacy non-Graph
    address) — that's discovered per-mailbox in _poll_one_mailbox,
    not filtered out here.
    """

    mailboxes = {settings.graph_mailbox_address.strip().lower()}

    async with AsyncSessionLocal() as db:
        client_inbox_emails = await ClientRepository(db).list_active_inbox_emails()
        category_inbox_emails = await CategoryRepository(db).list_active_inbox_emails()

    mailboxes.update(
        email.strip().lower() for email in client_inbox_emails if email
    )
    mailboxes.update(
        email.strip().lower() for email in category_inbox_emails if email
    )

    return sorted(mailboxes)


async def _seed_checkpoints_from_persisted_state_once() -> None:
    """
    Runs at most once per process — on the first tick after a (re)
    start, before any mailbox is polled — copying every persisted
    `mailbox_poll_state.checkpoint_at` into `_state.checkpoints` for
    any mailbox not already tracked in memory. This is what lets a
    restarted process resume roughly where the last one left off
    instead of always falling back to INITIAL_LOOKBACK_MINUTES. A
    failure here (DB unreachable at startup, etc.) is logged and
    otherwise ignored — every mailbox just keeps its normal
    INITIAL_LOOKBACK_MINUTES fallback for this process's lifetime,
    the exact pre-existing behavior.
    """

    if _state.checkpoints_seeded:
        return

    _state.checkpoints_seeded = True

    try:
        async with AsyncSessionLocal() as db:
            persisted = await MailboxPollStateRepository(db).get_all_checkpoints()
    except Exception:
        logger.exception(
            "Graph mail polling: failed to seed checkpoints from persisted "
            "mailbox_poll_state — every mailbox falls back to the "
            "%d-minute lookback for this process.",
            INITIAL_LOOKBACK_MINUTES,
        )
        return

    for mailbox_address, checkpoint_at in persisted.items():
        _state.checkpoints.setdefault(mailbox_address, checkpoint_at)


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

    await _seed_checkpoints_from_persisted_state_once()

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


async def _record_mailbox_fetch_failure_and_maybe_alert(
    settings: Settings, mailbox_address: str, *, error_summary: str
) -> None:
    """
    Persists a whole-mailbox fetch failure (a GraphAPIError before any
    message was even listed — never reaches inbound_mail_failures,
    which is per-message) and fires notify_mailbox_poll_stalled once
    this mailbox has been failing continuously for at least
    Settings.graph_mail_poll_stall_alert_minutes, at most once per
    stall (never re-alerts on every subsequent tick until either a
    real success resets it or the alert window has fully elapsed
    again). Entirely best-effort — any failure here is logged and
    swallowed, never allowed to affect the poll loop itself.
    """

    try:
        async with AsyncSessionLocal() as db:
            repository = MailboxPollStateRepository(db)
            await repository.record_failure(
                mailbox_address=mailbox_address, error_summary=error_summary
            )
            await db.commit()

            state = await repository.get(mailbox_address=mailbox_address)
            if state is None or state.last_success_at is None:
                return

            now = datetime.now(timezone.utc)
            stall_threshold = timedelta(minutes=settings.graph_mail_poll_stall_alert_minutes)
            has_stalled_long_enough = now - state.last_success_at >= stall_threshold
            already_alerted_this_stall = (
                state.last_alerted_at is not None
                and state.last_alerted_at >= state.last_success_at
                and now - state.last_alerted_at < stall_threshold
            )

            if has_stalled_long_enough and not already_alerted_this_stall:
                await notify_mailbox_poll_stalled(
                    db,
                    mailbox_address=mailbox_address,
                    consecutive_failures=state.consecutive_failures,
                    error_summary=error_summary,
                )
                await repository.mark_alerted(mailbox_address=mailbox_address)
                await db.commit()
    except Exception:
        logger.exception(
            "Graph mail polling: failed to record/alert on mailbox %s fetch failure",
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
        await _record_mailbox_fetch_failure_and_maybe_alert(
            settings, mailbox_address, error_summary=f"GraphAPIError({exc.status_code}): {exc}"
        )
        return
    except Exception:
        logger.exception(
            "Graph mail polling: failed to list new messages for mailbox %s",
            mailbox_address,
        )
        return

    processed = 0
    mailbox_failure_counts = _state.failure_counts.setdefault(mailbox_address, {})
    # The earliest still-unresolved (genuinely failed, not yet
    # dead-lettered) message's own receivedDateTime this tick — None
    # means every message this tick either stored successfully or hit
    # a terminal, non-retryable outcome (already processed/unknown
    # inbox). Determines how far the checkpoint is allowed to advance
    # below.
    earliest_unresolved_received_at: datetime | None = None

    for payload in messages:
        email_request = map_external_email_to_interaction(
            payload, landed_mailbox=mailbox_address
        )
        message_key = payload.internetMessageId

        files = None
        if payload.id and (
            payload.hasAttachments or body_references_inline_attachment(payload.body.content)
        ):
            try:
                attachments = await mail_provider_client.fetch_message_attachments(payload.id)
                files = build_upload_files_from_graph_attachments(attachments, payload.body.content)
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
                # A message that failed on an earlier tick and just
                # now succeeded no longer needs its retry count kept
                # around.
                mailbox_failure_counts.pop(message_key, None)

                # Phase 2 hardening: mark any prior persisted failure
                # record resolved. Its own inner try/except — a
                # diagnostic-write failure here must never surface as
                # a failure of this otherwise-successful poll.
                try:
                    await InboundMailFailureRepository(db).mark_resolved(
                        message_id=message_key, mailbox_address=mailbox_address
                    )
                    await db.commit()
                except Exception:
                    logger.exception(
                        "Failed to mark inbound_mail_failures resolved for %s",
                        message_key,
                    )
            except ValueError as exc:
                # "Email already processed." (overlap with a prior poll
                # or the webhook path already having caught it) and
                # "Unknown inbox address." are expected, non-exceptional,
                # TERMINAL outcomes here — log at info, not exception,
                # and never retry (there is nothing a retry could fix).
                await db.rollback()
                message = str(exc)
                if message == "Unknown inbox address.":
                    # Phase 2 hardening: previously silently dropped
                    # with no operational visibility at all — elevated
                    # to warning and given the same ops-notification
                    # EmailService's own shared-mailbox fallback
                    # already uses. Deliberately does NOT widen
                    # EmailService.receive_email itself (see
                    # notify_unmatched_inbox_email's own docstring) —
                    # no Client/Category/Interaction row is ever
                    # created here.
                    logger.warning(
                        "Graph poll: message %s landed at unmapped inbox "
                        "address %s with no matching Client/Category — "
                        "notifying Site Lead/Super Admin instead of "
                        "silently dropping.",
                        payload.internetMessageId,
                        mailbox_address,
                    )
                    try:
                        await notify_unmatched_inbox_email(
                            db,
                            from_email=email_request.from_email,
                            subject=email_request.subject,
                            mailbox_address=mailbox_address,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to notify ops of unmatched inbox address %s",
                            mailbox_address,
                        )
                else:
                    logger.info(
                        "Graph poll: message %s not stored: %s",
                        payload.internetMessageId,
                        exc,
                    )
                mailbox_failure_counts.pop(message_key, None)
            except Exception as exc:
                await db.rollback()

                if is_duplicate_message_id_violation(exc):
                    # Phase 2 hardening: the losing side of a benign
                    # concurrent-insert race (another poll tick, or the
                    # webhook transport, already stored this exact
                    # message) — never a genuine processing failure, so
                    # it must not be retry-counted or dead-lettered.
                    logger.info(
                        "Graph poll: message %s lost a concurrent insert "
                        "race — already processed by another worker/"
                        "transport; not retried.",
                        payload.internetMessageId,
                    )
                    mailbox_failure_counts.pop(message_key, None)
                    continue

                attempt = mailbox_failure_counts.get(message_key, 0) + 1
                mailbox_failure_counts[message_key] = attempt

                # Phase 2 hardening: persist a diagnostic record of this
                # genuine failure — backs, but never replaces, the
                # in-memory counter above (which still drives the real
                # retry/dead-letter decision). Its own inner try/except
                # — a DB hiccup writing this record must never crash
                # the batch or mask the real underlying failure.
                try:
                    await InboundMailFailureRepository(db).record_or_increment(
                        message_id=message_key,
                        mailbox_address=mailbox_address,
                        error_summary=f"{type(exc).__name__}: {exc}",
                    )
                    await db.commit()
                except Exception:
                    logger.exception(
                        "Failed to persist inbound_mail_failures row for %s",
                        message_key,
                    )

                if attempt >= MAX_MESSAGE_RETRY_ATTEMPTS:
                    # Dead-lettered: this message has now failed
                    # MAX_MESSAGE_RETRY_ATTEMPTS consecutive times.
                    # Logged distinctly (a real, alertable signal, not
                    # just another "processing failed" line) and
                    # allowed to stop holding back this mailbox's
                    # checkpoint — a retry has already been given a
                    # fair chance, and one permanently-broken message
                    # must not block every other message behind it
                    # forever.
                    logger.error(
                        "Graph poll: message %s failed %d consecutive times — "
                        "giving up on it (dead-lettered); it will not be "
                        "retried again automatically.",
                        payload.internetMessageId,
                        attempt,
                    )
                    mailbox_failure_counts.pop(message_key, None)
                else:
                    logger.exception(
                        "Graph poll: processing failed for message %s "
                        "(attempt %d/%d — will retry next tick)",
                        payload.internetMessageId,
                        attempt,
                        MAX_MESSAGE_RETRY_ATTEMPTS,
                    )
                    # Falls back to this tick's own start time if Graph
                    # genuinely omitted receivedDateTime (shouldn't
                    # happen — it's always requested via $select and
                    # this transport already orders by it — but never
                    # crash the poll loop over a missing optional
                    # field): re-checking from the start of this tick
                    # is a safe, if slightly wider, retry window.
                    received_at = payload.receivedDateTime or tick_started_at
                    if (
                        earliest_unresolved_received_at is None
                        or received_at < earliest_unresolved_received_at
                    ):
                        earliest_unresolved_received_at = received_at

    if earliest_unresolved_received_at is not None:
        # Hold the checkpoint back to just before the earliest
        # still-retryable failure's own arrival time, so the next
        # tick's `receivedDateTime gt since` filter re-includes it
        # (and, harmlessly, every already-successfully-stored message
        # after it — those are simply re-rejected as already-processed
        # by EmailService.receive_email's own dedupe check). This is
        # the fix for the previously-accepted gap where a failed
        # message was never retried by any later tick.
        new_checkpoint = earliest_unresolved_received_at - timedelta(microseconds=1)
    else:
        # Every message this tick either stored successfully or hit a
        # terminal, non-retryable outcome — safe to advance all the
        # way to when this tick started, same as before this fix.
        new_checkpoint = tick_started_at

    _state.checkpoints[mailbox_address] = new_checkpoint

    try:
        async with AsyncSessionLocal() as db:
            await MailboxPollStateRepository(db).record_success(
                mailbox_address=mailbox_address, checkpoint_at=new_checkpoint
            )
            await db.commit()
    except Exception:
        # A persistence failure here must never affect this tick's own
        # outcome — the in-memory checkpoint above is already
        # authoritative for this process's remaining lifetime; only a
        # future restart would miss out on resuming from this exact
        # point, falling back to INITIAL_LOOKBACK_MINUTES instead.
        logger.exception(
            "Graph mail polling: failed to persist checkpoint for mailbox %s",
            mailbox_address,
        )

    if messages:
        logger.info(
            "Graph mail polling: mailbox %s saw %d message(s), stored %d",
            mailbox_address,
            len(messages),
            processed,
        )

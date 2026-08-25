# graph_subscription_service.py
#
# Creates and renews the Microsoft Graph change-notification
# subscription that feeds POST /api/mail/incoming. A no-op wherever
# Graph isn't fully configured yet — matches every other Graph-adjacent
# module's "mock/no-op until credentials exist" convention (mail_provider.
# get_mail_provider_client(), core/email_sender.get_email_sender()). See
# app/core/graph_subscription_scheduler.py for the periodic trigger that
# calls ensure_subscription() below.

import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.core.config import Settings
from app.ticketing.services.graph_auth import GraphAuthClient, build_graph_auth_client
from app.ticketing.services.graph_retry import call_with_graph_retry

logger = logging.getLogger(__name__)

# Truncated in the notification body — this is Graph's own error JSON,
# not a customer email body/attachment/token, but still capped so the
# in-app notification never balloons.
_FAILURE_DETAIL_MAX_CHARS = 500


async def _notify_ops_of_subscription_failure(
    *, action: str, status_code: int, detail: str
) -> None:
    """
    Phase 2 hardening: subscription creation/renewal failure previously
    only logged at error level, with no operational alert — a lapsed
    webhook subscription silently stops all webhook-transport mail
    intake (polling, if configured, is unaffected either way).

    `action` is "creation" or "renewal". This module was previously
    entirely DB-free (only httpx calls) — opens its own short-lived
    AsyncSessionLocal session here, the same pattern
    app/core/sla_scheduler.py already uses for a DB write with no HTTP
    request in flight. Reuses the same Site Lead/Super Admin audience
    resolve_global_inbox_user_ids already established for the SLA
    breach notifier and EmailService's own shared-mailbox fallback —
    not a new alert channel.

    Deliberately wrapped in its own try/except: a failure to send this
    alert (e.g. a transient DB error) must never mask or crash the
    original creation/renewal failure path that's calling it — that
    path has already logged the real failure via logger.error before
    reaching this call.
    """

    try:
        # Deferred imports: this module is imported very early (it has
        # no DB/notification dependencies today), and importing these
        # at module level would add a DB/notifications dependency to
        # every caller of is_fully_configured/ensure_subscription even
        # when Graph isn't configured at all.
        from app.database.session import AsyncSessionLocal
        from app.notifications.repository import NotificationRepository
        from app.notifications.service import NotificationService, NotificationType
        from app.ticketing.repositories.user_repository import UserRepository
        from app.ticketing.services.sla_breach_notifier import (
            resolve_global_inbox_user_ids,
        )

        async with AsyncSessionLocal() as db:
            recipient_ids = await resolve_global_inbox_user_ids(UserRepository(db))
            await NotificationService(NotificationRepository(db)).notify(
                recipient_ids,
                NotificationType.GRAPH_SUBSCRIPTION_FAILED,
                title=f"Graph mail subscription {action} failed",
                message=f"status={status_code}: {detail[:_FAILURE_DETAIL_MAX_CHARS]}",
            )
            await db.commit()
    except Exception:
        logger.exception(
            "Failed to notify ops of Graph subscription %s failure", action
        )

# Graph enforces a hard ceiling of ~4230 minutes (~3 days) on a
# message-resource subscription's lifetime — there is no "forever"
# option; it must be actively renewed before it lapses.
SUBSCRIPTION_LIFETIME_MINUTES = 4230

# Renew once less than this much time remains before expiry. The
# scheduler ticks far more often than this margin (see
# graph_subscription_scheduler.py), so one missed tick is never a real
# risk of lapsing.
RENEWAL_MARGIN_MINUTES = 60 * 24  # 1 day


class _SubscriptionState:
    """
    Module-level, in-process only — deliberately not persisted to the
    database. A fresh process always creates a brand-new subscription
    on its first tick rather than trying to resume a previous
    process's; Graph tolerates multiple concurrent subscriptions on
    the same resource; this keeps the first pass simple rather than
    adding a persistence layer nobody has asked for yet (see
    EMAIL_INTEGRATION_CHECKLIST.md's note on this same tradeoff).
    """

    subscription_id: str | None = None
    expires_at: datetime | None = None


_state = _SubscriptionState()


def is_fully_configured(settings: Settings) -> bool:
    return bool(
        settings.graph_tenant_id
        and settings.graph_client_id
        and settings.graph_client_secret
        and settings.graph_mailbox_address
        and settings.graph_webhook_client_state
        and settings.graph_webhook_notification_url
    )


async def ensure_subscription(settings: Settings) -> None:
    """
    Idempotent: creates a subscription if none is currently tracked,
    or renews the tracked one if it's within RENEWAL_MARGIN_MINUTES of
    expiring. A no-op whenever Graph isn't fully configured.
    """

    if not is_fully_configured(settings):
        logger.debug(
            "Graph subscription check skipped — Graph integration not "
            "fully configured (tenant/client/secret/mailbox/clientState/"
            "notification URL)."
        )
        return

    auth_client = build_graph_auth_client(settings)
    if auth_client is None:
        # Unreachable given is_fully_configured() above, but never
        # trust that invariant blindly against a future edit to either
        # function independently.
        return

    now = datetime.now(timezone.utc)

    if _state.subscription_id is not None and _state.expires_at is not None:
        if _state.expires_at - now > timedelta(minutes=RENEWAL_MARGIN_MINUTES):
            return
        await _renew(settings, auth_client, now)
        return

    await _create(settings, auth_client, now)


async def _create(settings: Settings, auth_client: GraphAuthClient, now: datetime) -> None:
    expiration = now + timedelta(minutes=SUBSCRIPTION_LIFETIME_MINUTES)

    body = {
        "changeType": "created",
        "notificationUrl": settings.graph_webhook_notification_url,
        "resource": f"/users/{settings.graph_mailbox_address}/mailFolders('Inbox')/messages",
        "expirationDateTime": expiration.isoformat(),
        "clientState": settings.graph_webhook_client_state,
    }

    async def _attempt() -> httpx.Response:
        token = await auth_client.get_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.post(
                f"{settings.graph_api_base_url}/subscriptions",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )

    async def _force_refresh_token() -> None:
        await auth_client.get_token(force_refresh=True)

    response = await call_with_graph_retry(
        _attempt,
        operation="createSubscription",
        force_refresh_token=_force_refresh_token,
    )

    if response.status_code != 201:
        logger.error(
            "Graph subscription creation failed: status=%s body=%s",
            response.status_code,
            response.text,
        )
        await _notify_ops_of_subscription_failure(
            action="creation", status_code=response.status_code, detail=response.text
        )
        return

    data = response.json()
    _state.subscription_id = data["id"]
    _state.expires_at = expiration
    logger.info(
        "Graph subscription created: id=%s expires_at=%s",
        _state.subscription_id,
        expiration.isoformat(),
    )


async def _renew(settings: Settings, auth_client: GraphAuthClient, now: datetime) -> None:
    expiration = now + timedelta(minutes=SUBSCRIPTION_LIFETIME_MINUTES)

    async def _attempt() -> httpx.Response:
        token = await auth_client.get_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await client.patch(
                f"{settings.graph_api_base_url}/subscriptions/{_state.subscription_id}",
                headers={"Authorization": f"Bearer {token}"},
                json={"expirationDateTime": expiration.isoformat()},
            )

    async def _force_refresh_token() -> None:
        await auth_client.get_token(force_refresh=True)

    response = await call_with_graph_retry(
        _attempt,
        operation="renewSubscription",
        force_refresh_token=_force_refresh_token,
    )

    if response.status_code != 200:
        logger.error(
            "Graph subscription renewal failed for %s: status=%s body=%s — "
            "will attempt to create a fresh subscription next tick.",
            _state.subscription_id,
            response.status_code,
            response.text,
        )
        await _notify_ops_of_subscription_failure(
            action="renewal", status_code=response.status_code, detail=response.text
        )
        # Forget the stale id/expiry so the next tick creates a new
        # subscription rather than repeatedly trying to renew one
        # Graph may have already dropped.
        _state.subscription_id = None
        _state.expires_at = None
        return

    _state.expires_at = expiration
    logger.info(
        "Graph subscription renewed: id=%s new_expires_at=%s",
        _state.subscription_id,
        expiration.isoformat(),
    )

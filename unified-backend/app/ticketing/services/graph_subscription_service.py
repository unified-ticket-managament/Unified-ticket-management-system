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

logger = logging.getLogger(__name__)

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
    token = await auth_client.get_token()

    body = {
        "changeType": "created",
        "notificationUrl": settings.graph_webhook_notification_url,
        "resource": f"/users/{settings.graph_mailbox_address}/mailFolders('Inbox')/messages",
        "expirationDateTime": expiration.isoformat(),
        "clientState": settings.graph_webhook_client_state,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.graph_api_base_url}/subscriptions",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )

    if response.status_code != 201:
        logger.error(
            "Graph subscription creation failed: status=%s body=%s",
            response.status_code,
            response.text,
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
    token = await auth_client.get_token()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.patch(
            f"{settings.graph_api_base_url}/subscriptions/{_state.subscription_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"expirationDateTime": expiration.isoformat()},
        )

    if response.status_code != 200:
        logger.error(
            "Graph subscription renewal failed for %s: status=%s body=%s — "
            "will attempt to create a fresh subscription next tick.",
            _state.subscription_id,
            response.status_code,
            response.text,
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

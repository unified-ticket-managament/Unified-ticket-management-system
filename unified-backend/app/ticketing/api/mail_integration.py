# mail_integration.py
#
# The Microsoft Graph email integration layer. Three routes:
#
#   POST /api/mail/outgoing — accept a frontend-authored email
#   object, validate it, and dispatch it through MailProviderClient
#   (GraphMailProviderClient once Graph credentials are configured,
#   MockMailProviderClient otherwise — see mail_provider.py).
#
#   POST /api/mail/incoming — the real Graph webhook receiver.
#   Handles both of Graph's own request shapes to this one URL:
#     - The subscription validation handshake (a `validationToken`
#       query param, echoed back as plain text, no body).
#     - A live change-notification batch (a `value` array of
#       lightweight pointers — subscriptionId/clientState/resourceData.id
#       — never the message itself). Each notification's clientState is
#       verified before anything is trusted, then the full message is
#       fetched via MailProviderClient.fetch_message() and handed to
#       the existing, unmodified EmailService.receive_email — the same
#       core pipeline every other inbound transport already uses.
#     Processing happens in a background task after an immediate 202,
#     since Graph expects an ack within a few seconds and a fetch-plus-
#     full-pipeline run per notification can't be guaranteed to finish
#     that fast synchronously.
#
#   GET /api/mail/incoming — Graph also calls the notificationUrl with
#   GET for some validation retries in certain client libraries; kept
#   as a thin alias of the validationToken echo for compatibility.

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.core.config import get_settings
from app.database.session import AsyncSessionLocal, get_db
from app.dependencies.auth import get_current_agent
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.mail_integration import (
    GraphWebhookNotificationEnvelope,
    GraphWebhookNotificationItem,
    OutgoingEmailRequest,
    OutgoingEmailResponse,
)
from app.ticketing.services.attachment_service import AttachmentService
from app.ticketing.services.email_service import EmailService
from app.ticketing.services.mail_mapping_service import map_external_email_to_interaction
from app.ticketing.services.mail_provider import MailProviderClient, get_mail_provider_client
from app.ticketing.services.outgoing_mail_service import OutgoingMailService
from app.ticketing.services.sla_service import build_sla_service
from app.ticketing.storage import get_storage_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/mail",
    tags=["Mail Integration"],
)


def _build_outgoing_mail_service(db: AsyncSession) -> OutgoingMailService:
    return OutgoingMailService(
        client_repository=ClientRepository(db),
        # Swap point: get_mail_provider_client() returns a real
        # GraphMailProviderClient once Graph credentials are
        # configured, MockMailProviderClient otherwise.
        mail_provider_client=get_mail_provider_client(),
    )


def _build_email_service(db: AsyncSession) -> EmailService:
    """
    Mirrors app/ticketing/api/email.py's own builder of the same
    name (kept local rather than imported, since that one is
    module-private) — constructs the same EmailService so this
    module's inbound processing behaves identically to the existing
    form-encoded route.
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
    )


@router.post(
    "/outgoing",
    response_model=OutgoingEmailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send an outgoing email through the mail provider",
)
async def send_outgoing_email(
    request: OutgoingEmailRequest,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Accepts an email object authored by the frontend and dispatches
    it through MailProviderClient. Ticket-linked replies/composes
    keep using the existing /inbox/compose and reply endpoints
    unchanged — this route is the standalone provider-send primitive
    those flows could later be refactored to share.
    """

    service = _build_outgoing_mail_service(db)

    try:
        return await service.send_email(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _client_state_matches(item: GraphWebhookNotificationItem) -> bool:
    expected = get_settings().graph_webhook_client_state
    # No expected value configured means clientState verification can't
    # run yet (matches this module's mock-first, no-Azure-credentials-
    # required default elsewhere) — never silently accept in that case;
    # an unset secret must fail closed, not open.
    return bool(expected) and item.clientState == expected


async def _process_graph_notification(
    item: GraphWebhookNotificationItem, mail_provider_client: MailProviderClient
) -> None:
    """
    The background-task body for one notification item: verify
    clientState, fetch the real message via MailProviderClient, map it,
    and run it through the same EmailService.receive_email every other
    inbound transport uses. Runs with no HTTP request in flight and
    therefore no Depends(get_db) — opens its own session directly from
    AsyncSessionLocal and replicates get_db()'s own commit-on-success/
    rollback-on-error semantics by hand, the same pattern
    app/core/sla_scheduler.py already uses for its own background job.
    """

    if not _client_state_matches(item):
        logger.warning(
            "Graph webhook clientState mismatch or unconfigured — dropping "
            "notification for subscription %s",
            item.subscriptionId,
        )
        return

    try:
        payload = await mail_provider_client.fetch_message(item.resourceData.id)
    except Exception:
        logger.exception(
            "Failed to fetch Graph message %s for subscription %s",
            item.resourceData.id,
            item.subscriptionId,
        )
        return

    email_request = map_external_email_to_interaction(payload)

    async with AsyncSessionLocal() as db:
        try:
            service = _build_email_service(db)
            await service.receive_email(email_request)
            await db.commit()
        except ValueError as exc:
            # "Email already processed." (redelivery) and "Unknown inbox
            # address." are expected, non-exceptional outcomes for a
            # webhook — log at info, not exception, and don't retry.
            await db.rollback()
            logger.info(
                "Graph notification for message %s not stored: %s",
                item.resourceData.id,
                exc,
            )
        except Exception:
            await db.rollback()
            logger.exception(
                "Graph notification processing failed for message %s",
                item.resourceData.id,
            )


@router.post(
    "/incoming",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Microsoft Graph webhook receiver — validation handshake + change notifications",
)
async def receive_incoming_email(
    request: Request,
    background_tasks: BackgroundTasks,
    validationToken: str | None = Query(default=None),
):
    """
    Deliberately unauthenticated, same as POST /emails/incoming — this
    is a service-to-service transport route, not user-facing. Request
    authenticity for the notification path is instead enforced via
    clientState (see _client_state_matches), the mechanism Graph itself
    provides for exactly this purpose.

    Two distinct request shapes land on this one URL, matching Graph's
    own webhook contract:

    1. Subscription validation handshake — Graph calls this URL once
       when a subscription is created or renewed, with a
       `validationToken` query parameter and no meaningful body. Must
       be echoed back as plain text, synchronously, or subscription
       creation itself fails.
    2. A live change-notification batch — a JSON body shaped like
       GraphWebhookNotificationEnvelope (a `value` array of lightweight
       pointers, never the message content itself). Each item's
       clientState is verified, then processed in a background task
       (fetch the real message, map it, run EmailService.receive_email)
       after this route immediately returns 202 — Graph expects an ack
       within a few seconds, which a synchronous fetch-plus-full-
       pipeline run per notification can't reliably guarantee.
    """

    if validationToken is not None:
        return PlainTextResponse(content=validationToken, status_code=status.HTTP_200_OK)

    body = await request.json()
    envelope = GraphWebhookNotificationEnvelope.model_validate(body)

    mail_provider_client = get_mail_provider_client()

    for item in envelope.value:
        background_tasks.add_task(_process_graph_notification, item, mail_provider_client)

    return {"accepted": len(envelope.value)}


@router.get(
    "/incoming",
    summary="Validation-handshake alias for providers that probe with GET",
)
async def validate_incoming_webhook(validationToken: str | None = Query(default=None)):
    if validationToken is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="validationToken is required.",
        )

    return PlainTextResponse(content=validationToken, status_code=status.HTTP_200_OK)

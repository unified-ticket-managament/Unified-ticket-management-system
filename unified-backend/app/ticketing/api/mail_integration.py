# mail_integration.py
#
# The Graph-ready email integration layer, built ahead of Microsoft
# Graph API credentials being available. Two routes:
#
#   POST /api/mail/outgoing — accept a frontend-authored email
#   object, validate it, and dispatch it through MailProviderClient
#   (a mock today — see app/ticketing/services/mail_provider.py).
#
#   POST /api/mail/incoming — a JSON/Graph-shaped sibling of the
#   existing form-encoded POST /emails/incoming (app/ticketing/api/
#   email.py, unchanged). Accepts a realistic Microsoft Graph
#   `message` payload, maps it via map_external_email_to_interaction()
#   into the existing EmailRequest shape, then reuses the same,
#   unmodified EmailService.receive_email every other inbound
#   transport already goes through.
#
# Neither route touches Microsoft Graph authentication — that is
# deliberately out of scope until Azure AD app credentials exist.

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.email import EmailResponse
from app.ticketing.schemas.mail_integration import (
    IncomingMailPayload,
    OutgoingEmailRequest,
    OutgoingEmailResponse,
)
from app.ticketing.services.attachment_service import AttachmentService
from app.ticketing.services.email_service import EmailService
from app.ticketing.services.mail_mapping_service import map_external_email_to_interaction
from app.ticketing.services.mail_provider import get_mail_provider_client
from app.ticketing.services.outgoing_mail_service import OutgoingMailService
from app.ticketing.storage import get_storage_service

router = APIRouter(
    prefix="/api/mail",
    tags=["Mail Integration"],
)


def _build_outgoing_mail_service(db: AsyncSession) -> OutgoingMailService:
    return OutgoingMailService(
        client_repository=ClientRepository(db),
        # Swap point: get_mail_provider_client() returns the mock
        # today, a GraphMailProviderClient once credentials exist.
        mail_provider_client=get_mail_provider_client(),
    )


def _build_email_service(db: AsyncSession) -> EmailService:
    """
    Mirrors app/ticketing/api/email.py's own builder of the same
    name (kept local rather than imported, since that one is
    module-private) — constructs the same EmailService so the JSON
    incoming route below behaves identically to the existing
    form-encoded one.
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

    return EmailService(
        interaction_repository=interaction_repository,
        client_repository=client_repository,
        attachment_service=attachment_service,
        user_repository=user_repository,
        ticket_repository=TicketRepository(db),
        notification_service=NotificationService(NotificationRepository(db)),
    )


@router.post(
    "/outgoing",
    response_model=OutgoingEmailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send an outgoing email through the mail provider (mocked)",
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


@router.post(
    "/incoming",
    response_model=EmailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Receive an incoming email as a realistic Graph-shaped JSON payload",
)
async def receive_incoming_email(
    payload: IncomingMailPayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Deliberately unauthenticated, same as POST /emails/incoming —
    this is a service-to-service transport route, not user-facing.

    NOTE: a real Microsoft Graph webhook subscription requires
    validating a `validationToken` query param on the subscription
    handshake (echoed back as plain text) and checking `clientState`
    on every notification. Neither is implemented yet — this route
    only demonstrates accepting and mapping a Graph-shaped message
    body; don't point a live Graph subscription at it until that
    validation is added.
    """

    email_request = map_external_email_to_interaction(payload)
    service = _build_email_service(db)

    try:
        return await service.receive_email(email_request)
    except ValueError as exc:
        message = str(exc)

        if message == "Email already processed.":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)

        if message == "Unknown inbox address.":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import (
    InteractionRepository,
)
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.email import (
    EmailRequest,
    EmailResponse,
)
from app.ticketing.services.access_control import DUMMY_MAIL_ROLE_NAMES
from app.ticketing.services.attachment_service import AttachmentService
from app.ticketing.services.email_service import (
    EmailService,
)
from app.ticketing.storage import get_storage_service
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService

router = APIRouter(
    prefix="/emails",
    tags=["Emails"],
)


def _build_email_service(db: AsyncSession) -> tuple[EmailService, InteractionRepository]:
    interaction_repository = InteractionRepository(db)
    client_repository = ClientRepository(db)
    attachment_repository = AttachmentRepository(db)
    user_repository = UserRepository(db)

    attachment_service = AttachmentService(
        attachment_repository=attachment_repository,
        interaction_repository=interaction_repository,
        # Not used by validate_and_store_files (the only method this
        # intake path calls) — constructed for parity with the
        # ticket-upload path's AttachmentService.
        ticket_repository=TicketRepository(db),
        storage_service=get_storage_service(),
    )

    service = EmailService(
        interaction_repository=interaction_repository,
        client_repository=client_repository,
        attachment_service=attachment_service,
        user_repository=user_repository,
        ticket_repository=TicketRepository(db),
        notification_service=NotificationService(NotificationRepository(db)),
    )

    return service, interaction_repository


async def _receive_email(
    service: EmailService,
    email: EmailRequest,
    files: list[UploadFile],
) -> EmailResponse:
    try:
        return await service.receive_email(email, files=files)

    except ValueError as exc:

        message = str(exc)

        if message == "Email already processed.":

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=message,
            )

        if message == "Unknown inbox address.":

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=message,
            )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )


@router.post(
    "/incoming",
    response_model=EmailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def receive_email(
    to_email: str = Form(...),
    from_email: str = Form(...),
    from_name: str | None = Form(default=None),
    subject: str = Form(...),
    body: str = Form(...),
    html_body: str | None = Form(default=None),
    message_id: str = Form(...),
    received_at: datetime | None = Form(default=None),
    in_reply_to: str | None = Form(default=None),
    # Space-separated Message-IDs, matching the RFC 5322 References
    # header convention — split into a list before validation.
    references: str = Form(default=""),
    conversation_id: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
):
    """
    The real inbound-email transport route — service-to-service
    (N8N / the future Graph webhook), deliberately unauthenticated,
    same as before this feature. NOT the internal simulator; see
    POST /emails/dummy for that.
    """

    email = EmailRequest(
        to_email=to_email,
        from_email=from_email,
        from_name=from_name,
        subject=subject,
        body=body,
        html_body=html_body,
        message_id=message_id,
        received_at=received_at,
        in_reply_to=in_reply_to,
        references=references.split() if references else [],
        conversation_id=conversation_id,
    )

    service, _repository = _build_email_service(db)

    return await _receive_email(service, email, files)


@router.post(
    "/dummy",
    response_model=EmailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def receive_dummy_email(
    to_email: str = Form(...),
    from_email: str = Form(...),
    from_name: str | None = Form(default=None),
    subject: str = Form(...),
    body: str = Form(...),
    html_body: str | None = Form(default=None),
    message_id: str = Form(...),
    received_at: datetime | None = Form(default=None),
    in_reply_to: str | None = Form(default=None),
    references: str = Form(default=""),
    conversation_id: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    The internal "Create Dummy Mail" simulator — Site Lead only. Runs
    through the exact same EmailService.receive_email as the real
    transport route above (same threading/routing/audit behavior),
    the only difference is this route requires an authenticated Site
    Lead instead of being open. Kept as a separate route rather than
    role-gating /emails/incoming itself, since that one must stay
    reachable without a user Bearer token for the real webhook.
    """

    if current_user.role.name not in DUMMY_MAIL_ROLE_NAMES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Site Lead can create dummy mail.",
        )

    email = EmailRequest(
        to_email=to_email,
        from_email=from_email,
        from_name=from_name,
        subject=subject,
        body=body,
        html_body=html_body,
        message_id=message_id,
        received_at=received_at,
        in_reply_to=in_reply_to,
        references=references.split() if references else [],
        conversation_id=conversation_id,
    )

    service, _repository = _build_email_service(db)

    return await _receive_email(service, email, files)

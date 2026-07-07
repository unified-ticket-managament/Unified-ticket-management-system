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

from app.database.session import get_db
from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.client_repository import ClientRepository
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.repositories.ticket_repository import TicketRepository
from app.repositories.user_repository import UserRepository
from app.schemas.email import (
    EmailRequest,
    EmailResponse,
)
from app.services.attachment_service import AttachmentService
from app.services.email_service import (
    EmailService,
)
from app.storage import get_storage_service

router = APIRouter(
    prefix="/emails",
    tags=["Emails"],
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
    files: list[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
):

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
    )

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
    )

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

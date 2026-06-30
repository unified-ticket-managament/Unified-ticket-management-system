from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.repositories.interaction_repository import (
    InteractionRepository,
)
from app.schemas.email import (
    EmailRequest,
    EmailResponse,
)
from app.services.email_service import (
    EmailService,
)

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
    email: EmailRequest,
    db: AsyncSession = Depends(get_db),
):

    repository = InteractionRepository(db)

    service = EmailService(repository)

    try:
        return await service.receive_email(email)

    except ValueError as exc:

        message = str(exc)

        if message == "Email already processed.":

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=message,
            )

        if message == "Unknown client email.":

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=message,
            )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
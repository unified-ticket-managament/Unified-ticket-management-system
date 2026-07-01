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
from app.repositories.ticket_repository import TicketRepository
from app.repositories.user_repository import UserRepository
from app.schemas.email import (
    EmailRequest,
    EmailResponse,
)
from app.services.agent_assignment_service import (
    AgentAssignmentService,
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

    interaction_repository = InteractionRepository(db)
    user_repository = UserRepository(db)
    ticket_repository = TicketRepository(db)

    agent_assignment_service = AgentAssignmentService(
        user_repository=user_repository,
        ticket_repository=ticket_repository,
        interaction_repository=interaction_repository,
    )

    service = EmailService(
        interaction_repository=interaction_repository,
        user_repository=user_repository,
        agent_assignment_service=agent_assignment_service,
    )

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

        if message == "No active agents available.":

            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=message,
            )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )
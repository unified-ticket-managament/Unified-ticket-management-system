import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.session import get_db
from app.notifications.repository import NotificationRepository
from app.notifications.service import NotificationService
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.first_response_sla_repository import (
    FirstResponseSLARepository,
)
from app.ticketing.repositories.resolution_sla_repository import (
    ResolutionSLARepository,
)
from app.ticketing.repositories.sla_breach_notification_repository import (
    SLABreachNotificationRepository,
)
from app.ticketing.repositories.sla_policy_repository import SLAPolicyRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.schemas.sla import SLASweepResponse
from app.ticketing.services.sla_sweep_service import SLASweepService

#sla_internal.py

router = APIRouter(
    prefix="/internal/sla",
    tags=["SLA (internal)"],
)


async def verify_sla_sweep_secret(
    x_sla_sweep_secret: str = Header(...),
) -> None:
    """
    Shared-secret check, not JWT — there's no "user" behind a cron
    tick. Constant-time compare (secrets.compare_digest) so a timing
    side-channel can't be used to guess the secret byte-by-byte.
    """

    settings = get_settings()

    if not secrets.compare_digest(x_sla_sweep_secret, settings.sla_sweep_shared_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid sweep credentials.",
        )


@router.post(
    "/sweep",
    response_model=SLASweepResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_sla_sweep_secret)],
)
async def run_sla_sweep(
    db: AsyncSession = Depends(get_db),
):
    """
    The Render Cron Job's target — runs one breach-detection pass over
    every active SLA clock, firing at-risk/breached/escalated
    notifications idempotently. See SLASweepService for the full
    threshold/recipient logic.
    """

    service = SLASweepService(
        sla_policy_repository=SLAPolicyRepository(db),
        first_response_sla_repository=FirstResponseSLARepository(db),
        resolution_sla_repository=ResolutionSLARepository(db),
        sla_breach_notification_repository=SLABreachNotificationRepository(db),
        ticket_repository=TicketRepository(db),
        client_repository=ClientRepository(db),
        user_repository=UserRepository(db),
        notification_service=NotificationService(NotificationRepository(db)),
    )

    return await service.run_sweep()

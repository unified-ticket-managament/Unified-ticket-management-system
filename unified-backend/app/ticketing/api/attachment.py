# attachment.py

from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from shared_models.models import User

from app.database.session import get_db
from app.dependencies.auth import get_current_agent, get_current_user
from app.ticketing.repositories.attachment_repository import AttachmentRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.schemas.attachment import AttachmentMetadata
from app.ticketing.services.attachment_service import AttachmentService
from app.ticketing.storage import get_storage_service

router = APIRouter(
    prefix="/attachments",
    tags=["Attachments"],
)


def _build_service(db: AsyncSession) -> AttachmentService:
    return AttachmentService(
        attachment_repository=AttachmentRepository(db),
        interaction_repository=InteractionRepository(db),
        ticket_repository=TicketRepository(db),
        storage_service=get_storage_service(),
        client_repository=ClientRepository(db),
    )


@router.get(
    "/{attachment_id}",
    response_model=AttachmentMetadata,
)
async def get_attachment(
    attachment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = _build_service(db)
    return await service.get_attachment(attachment_id, current_user=current_user)


@router.get(
    "/{attachment_id}/download",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
)
async def download_attachment(
    attachment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Redirects to a short-lived presigned URL — bytes flow directly
    from object storage to the browser, not through this backend.
    """
    service = _build_service(db)
    url = await service.get_download_url(attachment_id, current_user=current_user)
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.delete(
    "/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_attachment(
    attachment_id: UUID,
    current_user: User = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
):
    service = _build_service(db)
    await service.delete_attachment(attachment_id, current_user=current_user)

# attachment.py

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.interaction_repository import InteractionRepository
from app.repositories.ticket_repository import TicketRepository
from app.repositories.user_repository import UserRepository
from app.schemas.attachment import AttachmentMetadata
from app.services.attachment_service import AttachmentService
from app.storage import get_storage_service

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
        user_repository=UserRepository(db),
    )


@router.get(
    "/{attachment_id}",
    response_model=AttachmentMetadata,
)
async def get_attachment(
    attachment_id: UUID,
    agent_name: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    service = _build_service(db)
    return await service.get_attachment(attachment_id, agent_name=agent_name)


@router.get(
    "/{attachment_id}/download",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
)
async def download_attachment(
    attachment_id: UUID,
    agent_name: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Redirects to a short-lived presigned URL — bytes flow directly
    from object storage to the browser, not through this backend.
    """
    service = _build_service(db)
    url = await service.get_download_url(attachment_id, agent_name=agent_name)
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.delete(
    "/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_attachment(
    attachment_id: UUID,
    agent_name: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    service = _build_service(db)
    await service.delete_attachment(attachment_id, agent_name=agent_name)

# attachment.py

from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
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


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Streams the attachment's bytes through this backend rather than
    redirecting to the storage provider's own URL — UTMS is served
    over plain HTTP, and a browser navigating from that page straight
    to an external HTTPS storage URL is what Chrome's "Insecure
    download blocked" warning was reacting to. Requires a real
    Authorization bearer token (not a query-param token), since this
    is called via an authenticated fetch/axios request, never a raw
    browser navigation.
    """
    service = _build_service(db)
    attachment, content = await service.download_attachment_content(
        attachment_id, current_user=current_user
    )
    ascii_filename = (
        attachment.filename.encode("ascii", "replace")
        .decode("ascii")
        .replace("\\", "_")
        .replace('"', "_")
        .translate({0x0D: None, 0x0A: None})
    )
    disposition = (
        f'attachment; filename="{ascii_filename}"; '
        f"filename*=UTF-8''{quote(attachment.filename)}"
    )
    return Response(
        content=content,
        media_type=attachment.mime_type or "application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


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

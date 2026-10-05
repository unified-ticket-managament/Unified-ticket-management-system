from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.dependencies.auth import get_current_active_user
from app.rbac.repositories.email_signature_repository import EmailSignatureRepository
from app.rbac.repositories.user_repository import UserRepository
from app.rbac.schemas.email_signature import (
    EmailSignatureCreate,
    EmailSignatureImageResponse,
    EmailSignatureListResponse,
    EmailSignatureResponse,
    EmailSignatureUpdate,
)
from app.rbac.services.email_signature_service import EmailSignatureService
from app.ticketing.storage import StorageConfigurationError, get_storage_service

# Self-service only, alongside GET/PATCH /auth/me — the same
# "my own profile" surface, with no user-id path parameter anywhere,
# so every call acts on the authenticated (effective, when
# impersonating) user and nobody else.
router = APIRouter(
    prefix="/auth/me",
    tags=["Email Signatures"],
)


def get_email_signature_service(
    db: AsyncSession = Depends(get_db),
) -> EmailSignatureService:
    try:
        storage_service = get_storage_service()
    except StorageConfigurationError:
        # Text-only signatures keep working without object storage;
        # only image upload/preview needs it (upload_image 503s).
        storage_service = None

    return EmailSignatureService(
        signature_repository=EmailSignatureRepository(db),
        user_repository=UserRepository(db),
        storage_service=storage_service,
    )


@router.get(
    "/signatures",
    response_model=EmailSignatureListResponse,
    summary="List My Email Signatures",
)
async def list_signatures(
    current_user=Depends(get_current_active_user),
    service: EmailSignatureService = Depends(get_email_signature_service),
):
    return await service.list_signatures(current_user)


@router.post(
    "/signatures",
    response_model=EmailSignatureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Email Signature",
)
async def create_signature(
    data: EmailSignatureCreate,
    current_user=Depends(get_current_active_user),
    service: EmailSignatureService = Depends(get_email_signature_service),
):
    return await service.create_signature(current_user, data)


@router.patch(
    "/signatures/{signature_id}",
    response_model=EmailSignatureResponse,
    summary="Update Email Signature",
)
async def update_signature(
    signature_id: UUID,
    data: EmailSignatureUpdate,
    current_user=Depends(get_current_active_user),
    service: EmailSignatureService = Depends(get_email_signature_service),
):
    return await service.update_signature(current_user, signature_id, data)


@router.delete(
    "/signatures/{signature_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Email Signature",
)
async def delete_signature(
    signature_id: UUID,
    current_user=Depends(get_current_active_user),
    service: EmailSignatureService = Depends(get_email_signature_service),
):
    await service.delete_signature(current_user, signature_id)


@router.post(
    "/signatures/{signature_id}/set-default",
    response_model=EmailSignatureResponse,
    summary="Set Default Email Signature",
)
async def set_default_signature(
    signature_id: UUID,
    current_user=Depends(get_current_active_user),
    service: EmailSignatureService = Depends(get_email_signature_service),
):
    return await service.set_default(current_user, signature_id)


@router.post(
    "/signature-images",
    response_model=EmailSignatureImageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Email Signature Image",
)
async def upload_signature_image(
    file: UploadFile = File(...),
    current_user=Depends(get_current_active_user),
    service: EmailSignatureService = Depends(get_email_signature_service),
):
    return await service.upload_image(current_user, file)

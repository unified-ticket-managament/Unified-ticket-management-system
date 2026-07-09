from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.ticketing.schemas.common import ORMBase

#schemas/attachement.py
class AttachmentCreate(BaseModel):
    interaction_id: UUID
    filename: str = Field(..., min_length=1, max_length=255)
    mime_type: str | None = Field(default=None, max_length=100)
    size_bytes: int | None = Field(default=None, ge=0)
    storage_key: str = Field(..., min_length=1)
    bucket_name: str | None = Field(default=None, max_length=255)
    scan_status: str = Field(default="pending", max_length=20)


class AttachmentResponse(ORMBase):
    attachment_id: UUID
    interaction_id: UUID
    filename: str
    mime_type: str | None
    size_bytes: int | None
    storage_key: str
    bucket_name: str | None
    scan_status: str
    uploaded_at: datetime
    created_at: datetime | None
    updated_at: datetime | None


class AttachmentMetadata(BaseModel):
    """
    API-facing attachment shape embedded in email/interaction
    responses. Built explicitly by the service (not derived via
    from_attributes) since it injects presigned URLs.
    """

    id: UUID
    filename: str
    mime_type: str | None
    size: int | None
    download_url: str
    preview_url: str | None = None


class AttachmentUploadResponse(BaseModel):
    """
    Response returned after files have been
    uploaded and recorded on the ticket timeline.
    """

    interaction_id: UUID
    ticket_id: UUID
    attachments: list[AttachmentMetadata]
    message: str
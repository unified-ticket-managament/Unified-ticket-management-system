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


class TicketAttachmentItem(BaseModel):
    """
    One row in a ticket's complete attachment history (GET
    /tickets/{id}/attachments) — the same AttachmentMetadata shape
    (id/filename/mime_type/size/download_url/preview_url) plus enough
    about the *owning* interaction (id/type/performer/timestamp) for
    the frontend to render "uploaded by X on Y" without a second
    lookup, mirroring the performed_by/performed_by_name/created_at
    fields InteractionResponse already carries for the same purpose.
    """

    id: UUID
    filename: str
    mime_type: str | None
    size: int | None
    download_url: str
    preview_url: str | None = None
    interaction_id: UUID
    interaction_type: str
    performed_by: UUID | None
    performed_by_name: str | None
    created_at: datetime


class AttachmentUploadResponse(BaseModel):
    """
    Response returned after files have been
    uploaded and recorded on the ticket timeline.
    """

    interaction_id: UUID
    ticket_id: UUID
    attachments: list[AttachmentMetadata]
    message: str
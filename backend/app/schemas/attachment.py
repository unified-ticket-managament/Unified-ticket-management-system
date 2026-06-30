from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMBase

#schemas/attachement.py
class AttachmentCreate(BaseModel):
    interaction_id: UUID
    filename: str = Field(..., min_length=1, max_length=255)
    mime_type: str | None = Field(default=None, max_length=100)
    size_bytes: int | None = Field(default=None, ge=0)
    storage_key: str = Field(..., min_length=1)
    scan_status: str = Field(default="pending", max_length=20)


class AttachmentResponse(ORMBase):
    attachment_id: UUID
    interaction_id: UUID
    filename: str
    mime_type: str | None
    size_bytes: int | None
    storage_key: str
    scan_status: str
    uploaded_at: datetime
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.ticketing.schemas.common import ORMBase


class MailFolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class MailFolderResponse(ORMBase):
    folder_id: UUID
    name: str
    created_by: UUID | None
    created_at: datetime

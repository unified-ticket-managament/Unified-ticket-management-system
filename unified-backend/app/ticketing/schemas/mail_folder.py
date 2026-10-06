from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.ticketing.schemas.common import ORMBase


def _clean_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Folder name cannot be blank.")
    return value


class MailFolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    # None = root folder; otherwise create as a subfolder of this one.
    parent_folder_id: UUID | None = None

    _strip = field_validator("name")(_clean_name)


class MailFolderRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

    _strip = field_validator("name")(_clean_name)


class MailFolderMove(BaseModel):
    # None = move to root.
    parent_folder_id: UUID | None = None


class MailFolderResponse(ORMBase):
    folder_id: UUID
    name: str
    parent_folder_id: UUID | None = None
    created_by: UUID | None
    created_at: datetime

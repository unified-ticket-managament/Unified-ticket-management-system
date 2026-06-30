from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import InteractionDirection, InteractionStatus
from app.schemas.common import ORMBase

#interaction.py
class InteractionCreate(BaseModel):
    ticket_id: UUID | None = None
    interaction_type: str = Field(..., min_length=1, max_length=50)
    status: InteractionStatus = InteractionStatus.PENDING
    direction: InteractionDirection
    performed_by: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    is_visible: bool = True
    message_id: str | None = Field(default=None, max_length=255)


class InteractionUpdate(BaseModel):
    ticket_id: UUID | None = None
    status: InteractionStatus | None = None
    payload: dict[str, Any] | None = None
    is_visible: bool | None = None
    removed_by: UUID | None = None
    removed_at: datetime | None = None


class InteractionResponse(ORMBase):
    interaction_id: UUID
    ticket_id: UUID | None
    interaction_type: str
    status: InteractionStatus
    direction: InteractionDirection
    performed_by: UUID | None
    payload: dict[str, Any]
    is_visible: bool
    removed_by: UUID | None
    removed_at: datetime | None
    message_id: str | None
    created_at: datetime
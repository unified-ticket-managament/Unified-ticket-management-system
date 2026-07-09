from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_id: UUID
    notification_type: str
    title: str
    message: str
    link: str | None
    related_entity_type: str | None
    related_entity_id: UUID | None
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    total: int
    unread_count: int
    items: list[NotificationResponse]


class MarkReadResponse(BaseModel):
    message: str

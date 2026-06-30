from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import TicketPriority, TicketStatus
from app.schemas.common import ORMBase

#ticket.py
class TicketCreate(BaseModel):
    client_id: UUID
    agent_id: UUID | None = None
    title: str = Field(..., min_length=1, max_length=255)
    ticket_type: str = Field(..., min_length=1, max_length=50)
    current_priority: TicketPriority = TicketPriority.MEDIUM
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class TicketUpdate(BaseModel):
    agent_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    ticket_type: str | None = Field(default=None, min_length=1, max_length=50)
    current_status: TicketStatus | None = None
    current_priority: TicketPriority | None = None
    custom_fields: dict[str, Any] | None = None
    closed_at: datetime | None = None
    version: int


class TicketResponse(ORMBase):
    ticket_id: UUID
    client_id: UUID
    agent_id: UUID | None
    title: str
    ticket_type: str
    current_status: TicketStatus
    current_priority: TicketPriority
    custom_fields: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
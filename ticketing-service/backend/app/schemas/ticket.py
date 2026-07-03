from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.enums import TicketPriority, TicketStatus
from app.schemas.common import ORMBase

#ticket.py
class TicketCreate(BaseModel):
    """
    Fields required to create a new ticket.

    current_status, version, and timestamps are
    set by the database / model defaults and are
    intentionally not accepted here.
    """

    client_id: UUID

    agent_id: UUID | None = None

    created_by: UUID | None = None

    title: str = Field(..., min_length=1, max_length=255)

    ticket_type: str = Field(..., min_length=1, max_length=50)

    current_priority: TicketPriority = TicketPriority.MEDIUM

    custom_fields: dict[str, Any] = Field(default_factory=dict)


class TicketUpdate(BaseModel):
    """
    Fields that may be updated on an existing ticket.

    All fields are optional; only the fields explicitly
    provided are applied (exclude_unset in the repository).
    """

    agent_id: UUID | None = None

    title: str | None = Field(default=None, min_length=1, max_length=255)

    ticket_type: str | None = Field(default=None, min_length=1, max_length=50)

    current_status: TicketStatus | None = None

    current_priority: TicketPriority | None = None

    custom_fields: dict[str, Any] | None = None

    closed_at: datetime | None = None


class TicketResponse(ORMBase):
    ticket_id: UUID
    client_id: UUID
    agent_id: UUID | None
    created_by: UUID | None
    title: str
    ticket_type: str
    current_status: TicketStatus
    current_priority: TicketPriority
    custom_fields: dict[str, Any]
    version: int
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    # Resolved from the `users` table by TicketService — not
    # persisted on the ticket row itself. None if the service
    # didn't attach them (e.g. lookup failed) or agent_id is null.
    client_name: str | None = None
    agent_name: str | None = None
    created_by_name: str | None = None
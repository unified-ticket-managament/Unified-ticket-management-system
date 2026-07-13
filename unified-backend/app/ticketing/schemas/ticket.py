from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.ticketing.enums import TicketPriority, TicketStatus
from app.ticketing.schemas.common import ORMBase

#ticket.py
class TicketCreate(BaseModel):
    """
    Fields required to create a new ticket.

    current_status, version, and timestamps are
    set by the database / model defaults and are
    intentionally not accepted here.
    """

    # Legacy — leave unset for new tickets. Use client_company_id.
    client_id: UUID | None = None

    client_company_id: UUID | None = None

    agent_id: UUID | None = None

    created_by: UUID | None = None

    title: str = Field(..., min_length=1, max_length=255)

    # The category name (e.g. "Eligibility", "AR", "Claims") from the
    # RBAC-owned `categories` table — GET /categories on this service
    # is what the frontend's dropdown is populated from. Plain string
    # here (not a fixed enum) since that table, not this schema, is
    # the source of truth and can grow without a code change.
    ticket_type: str = Field(..., min_length=1, max_length=100)

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

    ticket_type: str | None = Field(default=None, min_length=1, max_length=100)

    current_status: TicketStatus | None = None

    current_priority: TicketPriority | None = None

    custom_fields: dict[str, Any] | None = None

    closed_at: datetime | None = None


class RelatedTicketSummary(BaseModel):
    """
    Just enough to render a "Related Tickets" row/link — the full
    ticket is a separate `GET /tickets/{id}` away if the user clicks
    through.
    """

    ticket_id: UUID
    title: str
    current_status: TicketStatus


class RelateTicketRequest(BaseModel):
    related_ticket_id: UUID


class RelateTicketResponse(BaseModel):
    ticket_id: UUID
    related_ticket_id: UUID
    message: str


class UnrelateTicketResponse(BaseModel):
    message: str


class TicketResponse(ORMBase):
    ticket_id: UUID
    client_id: UUID | None
    client_company_id: UUID | None = None
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
    client_company_name: str | None = None
    agent_name: str | None = None
    created_by_name: str | None = None

    # Populated only on GET /tickets/{id} (not the list view, to
    # avoid an N+1 lookup per row) — see TicketService._attach_related_tickets.
    related_tickets: list[RelatedTicketSummary] = Field(default_factory=list)


class TicketListItemResponse(ORMBase):
    """
    GET /tickets (list) response shape — identical to TicketResponse
    minus `custom_fields` and `related_tickets`. `custom_fields` is
    arbitrary, unbounded JSONB that's only ever read on a single
    ticket's own detail view (confirmed unused by both frontends on a
    list row); `related_tickets` is never populated for list rows at
    all (`list_all` never calls `_attach_related_tickets` — that's
    detail-only), so it always serialized as an empty list here
    anyway. At production scale (thousands of tickets per page across
    thousands of clients), dropping an unbounded per-row JSONB blob
    that's dead weight on every list request adds up; GET /tickets/{id}
    is untouched and still returns the full TicketResponse.
    """

    ticket_id: UUID
    client_id: UUID | None
    client_company_id: UUID | None = None
    agent_id: UUID | None
    created_by: UUID | None
    title: str
    ticket_type: str
    current_status: TicketStatus
    current_priority: TicketPriority
    version: int
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    client_name: str | None = None
    client_company_name: str | None = None
    agent_name: str | None = None
    created_by_name: str | None = None


class DashboardStatsResponse(BaseModel):
    """
    GET /tickets/dashboard-stats -- every number/list the ticket-
    workspace Dashboard needs, computed server-side (see
    TicketService.get_dashboard_stats) instead of the browser fetching
    every visible ticket and deriving these client-side.
    """

    assigned: int
    open: int
    in_progress: int
    resolved: int
    resolved_today: int
    closed: int
    critical: int
    sla_risk: int
    recent_tickets: list[TicketListItemResponse]
    critical_tickets: list[TicketListItemResponse]

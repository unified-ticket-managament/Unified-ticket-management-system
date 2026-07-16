from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.ticketing.enums import EscalationLevel, EscalationStatus, TicketPriority, TicketStatus
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

    closed_by: UUID | None = None


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
    closed_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    # Resolved from the `users` table by TicketService — not
    # persisted on the ticket row itself. None if the service
    # didn't attach them (e.g. lookup failed) or agent_id is null.
    client_name: str | None = None
    client_company_name: str | None = None
    agent_name: str | None = None
    created_by_name: str | None = None
    closed_by_name: str | None = None

    # Populated only on GET /tickets/{id} (not the list view, to
    # avoid an N+1 lookup per row) — see TicketService._attach_related_tickets.
    related_tickets: list[RelatedTicketSummary] = Field(default_factory=list)

    # Escalation display fields — sourced from a LEFT JOIN against
    # ticket_escalations (see TicketRepository.list_visible_page), not
    # a second per-ticket lookup. `is_escalated` is the frontend's one
    # signal to render the Critical/escalation badge and, on My
    # Tickets, float the row to the top — deliberately NOT a change to
    # `current_priority` itself (see the plan's "effective display
    # priority" choice): a ticket's real business priority is never
    # silently overwritten by escalation state.
    is_escalated: bool = False
    escalation_level: EscalationLevel | None = None
    escalation_status: EscalationStatus | None = None
    escalation_ack_due_at: datetime | None = None

    # True only when the *viewing* user's own id is currently listed in
    # the escalation's owner_ids — i.e. the chain has actually reached
    # them, not just "this ticket happens to be escalated to someone."
    # Frontend gates the Acknowledge/Assign action on this rather than
    # on is_escalated alone: a ticket escalated from Staff to Team Lead
    # is still visible to an Account Manager on the unrestricted "All"
    # tab (that tab shows everything, by design), but they are not yet
    # a real owner, and an Acknowledge click from them would 403 — this
    # field lets the UI simply not offer that action instead of showing
    # a button that's guaranteed to fail. Deliberately per-viewer, so
    # it is NOT cacheable/shared across different users' requests for
    # the same ticket.
    is_escalation_owner: bool = False

    # Resolution SLA clock's own risk tier — sourced from a LEFT JOIN
    # against resolution_slas/sla_policies (see TicketRepository.
    # list_visible_page / _resolution_sla_tier_case), independent of
    # is_escalated above: a ticket can be at_risk with no active
    # escalation, or escalated with a healthy-looking clock (already
    # acknowledged, handling-SLA still fresh). None when there's no
    # active Resolution SLA clock or no matching policy.
    resolution_sla_tier: Literal["healthy", "at_risk", "breached", "escalated"] | None = None


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

    # See TicketResponse's own matching fields for the full rationale
    # — same LEFT JOIN-sourced, display-only escalation signal.
    is_escalated: bool = False
    escalation_level: EscalationLevel | None = None
    escalation_status: EscalationStatus | None = None
    escalation_ack_due_at: datetime | None = None

    # See TicketResponse's own matching field for the full rationale —
    # whether the *viewing* user is a current owner of this ticket's
    # escalation, not just whether it's escalated at all.
    is_escalation_owner: bool = False

    # See TicketResponse's own matching field for the full rationale.
    resolution_sla_tier: Literal["healthy", "at_risk", "breached", "escalated"] | None = None


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


class SLAOverviewCountsResponse(BaseModel):
    """
    GET /tickets/sla-overview-counts — the Dashboard's "SLA Overview"
    tile row, computed server-side in one grouped query (see
    TicketRepository.sla_overview_counts) instead of the browser
    fetching every visible ticket and calling GET /tickets/{id}/sla
    once per ticket to classify it.
    """

    running: int
    paused: int
    at_risk: int
    breached: int
    escalated: int
    completed: int

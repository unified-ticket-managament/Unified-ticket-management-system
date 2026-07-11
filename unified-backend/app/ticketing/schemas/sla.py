from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.ticketing.enums import SLAClockStatus, TicketPriority
from app.ticketing.schemas.common import ORMBase

#sla.py

class SLAPolicyResponse(ORMBase):
    """A single priority's First Response / Resolution SLA targets."""

    policy_id: UUID
    priority: TicketPriority
    first_response_target_minutes: int
    resolution_target_minutes: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SLAPolicyUpdate(BaseModel):
    """
    Partial update for one policy row. Only Site Lead/Super Admin may
    call this — see access_control.ensure_can_manage_sla_policies.
    """

    first_response_target_minutes: int | None = Field(default=None, gt=0)
    resolution_target_minutes: int | None = Field(default=None, gt=0)
    is_active: bool | None = None


class FirstResponseSLAState(BaseModel):
    """
    Current state of a ticket's First Response clock, as read at
    request time — `elapsed_fraction` is computed lazily here (never
    stored), matching this codebase's existing snoozed_until/expires_at
    lazy-evaluation idiom.
    """

    status: SLAClockStatus
    started_at: datetime
    due_at: datetime
    completed_at: datetime | None
    completion_reason: str | None
    elapsed_fraction: float


class ResolutionSLAState(BaseModel):
    """Current state of a ticket's Resolution clock, as read at request time."""

    status: SLAClockStatus
    started_at: datetime
    due_at: datetime
    paused_at: datetime | None
    total_paused_seconds: int
    completed_at: datetime | None
    elapsed_fraction: float


class TicketSLAResponse(BaseModel):
    """GET /tickets/{ticket_id}/sla — both clocks for a single ticket."""

    ticket_id: UUID
    first_response: FirstResponseSLAState | None
    resolution: ResolutionSLAState | None


class SLAPauseRequest(BaseModel):
    """Manual SLA pause override — a business exception, not routine agent work."""

    reason: str = Field(..., min_length=1, max_length=500)


class SLASweepResponse(BaseModel):
    """
    Returned by POST /internal/sla/sweep — surfaced in the Render Cron
    Job's own logs, and asserted on directly by the sweep's test suite.
    """

    first_response_at_risk: int
    first_response_breached: int
    resolution_at_risk: int
    resolution_breached: int
    resolution_escalated: int
    notifications_sent: int

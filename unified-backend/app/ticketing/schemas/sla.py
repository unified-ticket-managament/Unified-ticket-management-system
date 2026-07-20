from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.ticketing.enums import EscalationLevel, EscalationStatus, SLAClockStatus, TicketPriority
from app.ticketing.schemas.common import ORMBase

#sla.py

class SLAPolicyResponse(ORMBase):
    """A single priority's First Response / Resolution SLA targets."""

    policy_id: UUID
    priority: TicketPriority
    first_response_target_minutes: int
    resolution_target_minutes: int
    escalation_ack_target_minutes: int
    handling_sla_percentage: float
    handling_stage_percentages: list[float]
    warning_1_percentage: float
    warning_2_percentage: float
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
    escalation_ack_target_minutes: int | None = Field(default=None, gt=0)
    handling_sla_percentage: float | None = Field(default=None, ge=1, le=100)
    handling_stage_percentages: list[float] | None = Field(default=None, min_length=1)
    warning_1_percentage: float | None = Field(default=None, ge=1, le=100)
    warning_2_percentage: float | None = Field(default=None, ge=1, le=100)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _ensure_handling_stage_percentages_in_bounds(self) -> "SLAPolicyUpdate":
        """Same 1-100 bound the single handling_sla_percentage field enforces per-element, since Field(ge=/le=) can't reach into a list."""

        if self.handling_stage_percentages is not None:
            for value in self.handling_stage_percentages:
                if not (1 <= value <= 100):
                    raise ValueError(
                        "Every handling_stage_percentages value must be between 1 and 100."
                    )
        return self

    @model_validator(mode="after")
    def _ensure_warning_order_when_both_provided(self) -> "SLAPolicyUpdate":
        """
        Fast-fail defense-in-depth for the common case (this schema's
        one real caller, the SLA Timing Matrix page, always submits
        both fields together) — warning_1_percentage ("Half Elapsed")
        must fire before warning_2_percentage ("At Risk") as elapsed
        time increases, or the tiers are inverted (e.g. 90/50 would
        make "At Risk" trigger before "Half Elapsed" already had).
        This can't catch every case on its own — a request updating
        only one of the two fields against an existing, now-inconsistent
        stored value needs the merged current+incoming check in
        SLAService.update_policy instead; this only covers a single
        request that supplies a bad pair outright.
        """

        if (
            self.warning_1_percentage is not None
            and self.warning_2_percentage is not None
            and self.warning_1_percentage >= self.warning_2_percentage
        ):
            raise ValueError(
                "warning_1_percentage must be less than warning_2_percentage "
                "(Warning 1 must fire before Warning 2)."
            )
        return self


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
    """
    Current state of a ticket's Resolution clock, as read at request
    time. `active_target_minutes` is the real target this clock is
    currently measured against — read this directly rather than
    re-deriving a target from priority, since once a handling stage has
    reshifted the clock, its target no longer matches any single
    priority's flat policy value.
    """

    status: SLAClockStatus
    started_at: datetime
    due_at: datetime
    active_target_minutes: int
    paused_at: datetime | None
    total_paused_seconds: int
    completed_at: datetime | None
    elapsed_fraction: float


class TicketEscalationState(BaseModel):
    """
    Current state of a ticket's internal escalation chain, if any —
    entirely separate from `resolution`/`first_response` above: this
    never reflects a restarted or recalculated SLA, only who currently
    owns follow-up and by when they must acknowledge. `owner_names` is
    resolved alongside `owner_ids` (never a separate frontend lookup).
    `overdue_seconds` is 0 once acknowledged/closed, and computed
    lazily at request time otherwise — same idiom as elapsed_fraction
    above.
    """

    escalation_id: UUID
    level: EscalationLevel
    status: EscalationStatus
    owner_ids: list[UUID]
    owner_names: list[str]
    triggered_by: str
    created_at: datetime
    level_started_at: datetime
    ack_due_at: datetime
    acknowledged_at: datetime | None
    closed_at: datetime | None
    closed_reason: str | None
    overdue_seconds: float
    handling_stage: int
    handling_stage_started_at: datetime | None
    handling_stage_due_at: datetime | None


class EscalationHandlingSLAState(BaseModel):
    """
    Current state of the internal escalation-handling clock — a
    second, entirely separate timer from `resolution` above, measuring
    how long the current escalation owner has to actually resolve (not
    just acknowledge) the ticket. `target_seconds` is the resolved
    25%-of-original-target duration snapshotted at start time (see
    EscalationHandlingSLA's own model docstring for why it's stored,
    not re-derived from the live policy on every read).
    """

    status: SLAClockStatus
    target_seconds: int
    started_at: datetime
    due_at: datetime
    breached_at: datetime | None
    completed_at: datetime | None
    remaining_seconds: float


class TicketSLAResponse(BaseModel):
    """GET /tickets/{ticket_id}/sla — both clocks for a single ticket."""

    ticket_id: UUID
    first_response: FirstResponseSLAState | None
    resolution: ResolutionSLAState | None
    escalation: TicketEscalationState | None = None
    escalation_handling_sla: EscalationHandlingSLAState | None = None


class SLAPauseRequest(BaseModel):
    """Manual SLA pause override — a business exception, not routine agent work."""

    reason: str = Field(..., min_length=1, max_length=500)


class SLASweepResponse(BaseModel):
    """
    Returned by POST /internal/sla/sweep — surfaced in the Render Cron
    Job's own logs, and asserted on directly by the sweep's test suite.
    """

    first_response_half_elapsed: int
    first_response_at_risk: int
    first_response_breached: int
    resolution_half_elapsed: int
    resolution_at_risk: int
    resolution_breached: int
    resolution_escalated: int
    notifications_sent: int
    escalations_created: int
    escalations_advanced: int
    escalation_handling_sla_breaches: int
    errors: int

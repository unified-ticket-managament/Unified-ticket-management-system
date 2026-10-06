from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.ticketing.enums import SLAClockStatus, TicketPriority, TicketStatus


class AssignmentSLARunState(BaseModel):
    """One Resolution SLA run of one assignee (never a category)."""

    assignment_sla_id: UUID
    run_number: int
    priority: TicketPriority
    status: SLAClockStatus
    started_at: datetime
    due_at: datetime
    active_target_minutes: int
    paused_at: datetime | None
    total_paused_seconds: int
    completed_at: datetime | None
    completion_reason: str | None
    breached: bool
    breached_at: datetime | None
    remaining_seconds: int | None = Field(
        description="Seconds until due_at for a RUNNING/PAUSED run (negative once overdue); null when completed."
    )
    elapsed_fraction: float | None


class TicketAssignmentItem(BaseModel):
    assignment_id: UUID
    user_id: UUID
    user_name: str | None
    is_primary: bool
    status: TicketStatus
    assigned_by: UUID | None
    assigned_by_name: str | None
    assigned_at: datetime
    status_changed_at: datetime | None
    closed_at: datetime | None
    resolution_sla: AssignmentSLARunState | None = Field(
        description="The current (latest) run — live if one exists, else the most recent completed one."
    )
    sla_history: list[AssignmentSLARunState] = Field(default_factory=list)


class TicketCategoryItem(BaseModel):
    category_id: UUID
    category_name: str
    is_primary: bool
    assigned_at: datetime


class TicketAssignmentsResponse(BaseModel):
    ticket_id: UUID
    ticket_status: TicketStatus
    is_closed: bool
    closed_at: datetime | None
    closed_by: UUID | None
    assignments: list[TicketAssignmentItem]
    categories: list[TicketCategoryItem]


class AssignUsersRequest(BaseModel):
    """
    Assign one or many users in one all-or-nothing request. The backend
    re-validates every user and the primary choice — nothing here is
    trusted for authorization.
    """

    user_ids: list[UUID] = Field(..., min_length=1, max_length=50)
    primary_user_id: UUID | None = Field(
        default=None,
        description=(
            "Optional. Required in effect only to change an existing "
            "primary; a ticket with no primary yet defaults to the first "
            "listed user."
        ),
    )


class UpdateAssignmentRequest(BaseModel):
    status: TicketStatus | None = None
    is_primary: bool | None = Field(
        default=None,
        description="true promotes this assignee to primary. false is not accepted — promote someone else instead.",
    )

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.status is None and self.is_primary is None:
            raise ValueError("Provide status and/or is_primary.")
        if self.is_primary is False:
            raise ValueError("To change the primary, promote another assignee (is_primary=true).")
        return self


class AddTicketCategoryRequest(BaseModel):
    category_id: UUID


class TicketAssigneeSummary(BaseModel):
    """Compact per-assignee view embedded in ticket list/detail rows."""

    assignment_id: UUID
    user_id: UUID
    user_name: str | None
    is_primary: bool
    status: TicketStatus


class TicketCategorySummary(BaseModel):
    category_id: UUID
    category_name: str
    is_primary: bool

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, field_validator


class PermissionRequestCreate(BaseModel):
    permission_id: UUID
    # The specific person picked in the "Request To" dropdown — the
    # actual routing target. requested_role is no longer submitted by
    # the client at all; the backend derives it from this user's own
    # role at creation time (see PermissionRequestService.create_request).
    selected_approver_id: UUID
    reason: str
    scope_ticket_id: UUID | None = None


class PermissionRequestApprove(BaseModel):
    expires_at: datetime | None = None
    review_comment: str | None = None

    @field_validator("expires_at")
    @classmethod
    def expires_at_must_be_future(cls, value: datetime | None) -> datetime | None:
        if value is not None and value <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future.")
        return value


class PermissionRequestReject(BaseModel):
    review_comment: str | None = None


class PermissionRequestRevoke(BaseModel):
    reason: str | None = None


class PermissionRequestResponse(BaseModel):
    request_id: UUID
    requester_id: UUID
    requester_name: str | None = None
    permission_id: UUID
    permission_name: str
    requested_role: str
    selected_approver_id: UUID | None = None
    selected_approver_name: str | None = None
    reason: str
    scope_ticket_id: UUID | None = None
    status: str
    reviewed_by: UUID | None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None
    review_comment: str | None
    expires_at: datetime | None
    granted_override_id: UUID | None
    revoked_at: datetime | None = None
    revoked_by: UUID | None = None
    revoked_by_name: str | None = None
    revoke_reason: str | None = None
    # Computed per-viewer: whether the user this response is being
    # returned to is allowed to revoke this specific request (the
    # original approver, or Super Admin) — lets the frontend gate the
    # Revoke button without re-implementing that authorization rule.
    can_revoke: bool = False
    created_at: datetime


class EligibleApproverRolesResponse(BaseModel):
    roles: list[str]


class EligibleApproverUser(BaseModel):
    user_id: UUID
    name: str
    role_name: str


class TeammateStaffOption(BaseModel):
    user_id: UUID
    name: str


class TeammateTicketOption(BaseModel):
    ticket_id: UUID
    title: str
    current_status: str

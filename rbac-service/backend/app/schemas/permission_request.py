from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, field_validator


class PermissionRequestCreate(BaseModel):
    permission_id: UUID
    requested_role: str
    reason: str


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


class PermissionRequestResponse(BaseModel):
    request_id: UUID
    requester_id: UUID
    requester_name: str | None = None
    permission_id: UUID
    permission_name: str
    requested_role: str
    reason: str
    status: str
    reviewed_by: UUID | None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None
    review_comment: str | None
    expires_at: datetime | None
    granted_override_id: UUID | None
    revoked_at: datetime | None = None
    created_at: datetime


class EligibleApproverRolesResponse(BaseModel):
    roles: list[str]

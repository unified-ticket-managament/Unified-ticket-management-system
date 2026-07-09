from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class GrantOverrideRequest(BaseModel):
    permission_id: UUID
    reason: str | None = None
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def expires_at_must_be_future(cls, value: datetime | None) -> datetime | None:
        if value is not None and value <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future.")
        return value


class PermissionOverrideResponse(BaseModel):
    override_id: UUID
    user_id: UUID
    permission_id: UUID
    permission_name: str
    granted_by: UUID | None
    reason: str | None
    granted_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    revoked_by: UUID | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)

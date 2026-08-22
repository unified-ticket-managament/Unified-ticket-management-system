from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ImpersonationStartRequest(BaseModel):
    target_user_id: UUID


class ImpersonationTargetSummary(BaseModel):
    user_id: UUID
    name: str
    role: str


class ImpersonationStartResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime
    target_user: ImpersonationTargetSummary

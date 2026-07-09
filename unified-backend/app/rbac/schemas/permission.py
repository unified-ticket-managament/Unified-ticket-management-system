from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.rbac.schemas.common import ORMBase


class PermissionBase(BaseModel):
    permission_name: str
    description: str | None = None


class PermissionCreate(PermissionBase):
    pass


class PermissionUpdate(BaseModel):
    permission_name: str | None = None
    description: str | None = None


class PermissionResponse(ORMBase):
    permission_id: UUID
    permission_name: str
    description: str | None
    created_at: datetime


class PermissionListResponse(BaseModel):
    permissions: list[PermissionResponse]
    total: int
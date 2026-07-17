from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ReportingManagerAssign(BaseModel):
    account_manager_id: UUID
    category_id: UUID


class ReportingManagerResponse(BaseModel):
    id: UUID
    account_manager_id: UUID
    account_manager_name: str
    category_id: UUID
    category_name: str
    assigned_by: UUID | None = None
    assigned_by_name: str | None = None
    assigned_at: datetime


class ReportingManagerListResponse(BaseModel):
    items: list[ReportingManagerResponse]

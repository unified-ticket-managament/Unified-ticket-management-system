from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# -----------------------------
# Base Schema
# -----------------------------

class AuditLogBase(BaseModel):
    action: str
    entity_type: str
    entity_id: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None


# -----------------------------
# Create Audit Log
# -----------------------------

class AuditLogCreate(AuditLogBase):
    user_id: UUID | None = None


# -----------------------------
# Audit Log Response
# -----------------------------

class AuditLogResponse(AuditLogBase):
    audit_log_id: UUID
    user_id: UUID | None = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)


# -----------------------------
# Audit Log List
# -----------------------------

class AuditLogListResponse(BaseModel):
    logs: list[AuditLogResponse]
    total: int
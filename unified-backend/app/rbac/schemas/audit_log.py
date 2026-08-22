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

    # Set only for a row written during an active "Login as User"
    # session — the real, physically-authenticated Super Admin,
    # distinct from `user_id` above (which stays whoever's identity
    # actually governed the request). None for every ordinary row —
    # see root CLAUDE.md's impersonation plan / app/core/
    # impersonation_context.py.
    impersonator_id: UUID | None = None
    impersonator_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


# -----------------------------
# Audit Log List
# -----------------------------

class AuditLogListResponse(BaseModel):
    logs: list[AuditLogResponse]
    total: int
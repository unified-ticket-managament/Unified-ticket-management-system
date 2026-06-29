"""
Application models.

User and Role are imported from the shared-models package.

RBAC owns:
    - Permission
    - RolePermission
    - AuditLog
"""

from shared_models.database import Base
from shared_models.models import User, Role

from app.models.permission import Permission
from app.models.role_permission import RolePermission
from app.models.audit_log import AuditLog

__all__ = [
    "Base",
    "User",
    "Role",
    "Permission",
    "RolePermission",
    "AuditLog",
]
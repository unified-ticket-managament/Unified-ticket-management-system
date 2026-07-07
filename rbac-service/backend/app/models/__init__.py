"""
Application models.

User, Role, and Category are imported from the shared-models package
(Category is read by the ticketing service too, for its ticket-creation
category dropdown — see shared_models/shared_models/models/category.py).

RBAC owns:
    - Permission
    - RolePermission
    - AuditLog
"""

from shared_models.database import Base
from shared_models.models import User, Role, Category

from app.models.permission import Permission
from app.models.role_permission import RolePermission
from app.models.audit_log import AuditLog

__all__ = [
    "Base",
    "User",
    "Role",
    "Category",
    "Permission",
    "RolePermission",
    "AuditLog",
]
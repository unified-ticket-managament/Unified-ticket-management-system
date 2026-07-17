"""
Application models.

User, Role, and Category are imported from the shared-models package
(Category is read by the ticketing service too, for its ticket-creation
category dropdown — see shared_models/shared_models/models/category.py).

RBAC owns:
    - Permission
    - RolePermission
    - AuditLog
    - UserPermissionOverride
    - PermissionRequest
    - ReportingManagerTeam
"""

from shared_models.database import Base
from shared_models.models import User, Role, Category

from app.rbac.models.permission import Permission
from app.rbac.models.role_permission import RolePermission
from app.rbac.models.audit_log import AuditLog
from app.rbac.models.permission_override import UserPermissionOverride
from app.rbac.models.permission_request import PermissionRequest
from app.rbac.models.reporting_manager_team import ReportingManagerTeam

__all__ = [
    "Base",
    "User",
    "Role",
    "Category",
    "Permission",
    "RolePermission",
    "AuditLog",
    "UserPermissionOverride",
    "PermissionRequest",
    "ReportingManagerTeam",
]
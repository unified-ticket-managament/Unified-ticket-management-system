# grant_view_escalated_permission.py
#
# One-time, non-destructive grant for the ticket-level "View Escalated
# Tickets" visibility feature: `ticket:view_escalated` was previously
# Override-only for Staff (Full for every other role already, per
# seed.py's DEFAULT_ROLES) — the new feature requires it Full for every
# agent role by default, so this backfills the one missing
# (Staff, ticket:view_escalated) RolePermission row against the live
# database rather than waiting for a full reseed. Uses the same
# RolePermissionService.assign_permission the "Manage Permissions" UI
# itself calls (actor=None skips the permission-to-grant-permissions
# check, same convention a script run by an operator already implies),
# so every existing Staff user's `permission_version` is bumped too —
# their next request picks up the new permission within one RBAC-cache
# TTL, no separate step needed. Idempotent: does nothing if the grant
# already exists (e.g. seed.py's own additive loop got there first).
#
# Usage (from unified-backend/, with the venv active):
#   python -m scripts.rbac_seed.grant_view_escalated_permission

import asyncio

from app.database.session import AsyncSessionLocal
from app.rbac.repositories import (
    AuditLogRepository,
    PermissionRepository,
    RolePermissionRepository,
    RoleRepository,
    UserRepository,
)
from app.rbac.services.audit_log_service import AuditLogService
from app.rbac.services.role_permission_service import RolePermissionService

PERMISSION_NAME = "ticket:view_escalated"
ROLE_NAME = "Staff"


async def main() -> None:
    async with AsyncSessionLocal() as session:
        role_repository = RoleRepository(session)
        permission_repository = PermissionRepository(session)
        role_permission_repository = RolePermissionRepository(session)
        user_repository = UserRepository(session)
        audit_log_service = AuditLogService(AuditLogRepository(session))

        role = await role_repository.get_by_name(ROLE_NAME)
        if role is None:
            print(f"Role {ROLE_NAME!r} not found — nothing to do.")
            return

        permission = await permission_repository.get_by_name(PERMISSION_NAME)
        if permission is None:
            print(f"Permission {PERMISSION_NAME!r} not found — run the main seed first.")
            return

        existing = await role_permission_repository.get_permissions_by_role(role.role_id)
        if any(p.permission_id == permission.permission_id for p in existing):
            print(f"{ROLE_NAME} already has {PERMISSION_NAME} — nothing to do.")
            return

        service = RolePermissionService(
            role_repository=role_repository,
            permission_repository=permission_repository,
            role_permission_repository=role_permission_repository,
            user_repository=user_repository,
            audit_log_service=audit_log_service,
        )
        await service.assign_permission(role.role_id, permission.permission_id, actor=None)
        await session.commit()

        print(f"Granted {PERMISSION_NAME} to {ROLE_NAME} and bumped permission_version for its users.")


if __name__ == "__main__":
    asyncio.run(main())

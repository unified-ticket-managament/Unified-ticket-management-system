import asyncio
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import User, Role
from app.database.session import AsyncSessionLocal, engine
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.permission_override_repository import PermissionOverrideRepository
from app.rbac.services.permission_resolver import PermissionResolverService
from app.rbac.models.permission import Permission
from app.rbac.models.role_permission import RolePermission

async def main():
    async with AsyncSessionLocal() as session:
        uresult = await session.execute(
            select(User).options(joinedload(User.role))
            .where(User.user_id == "ed6d65d0-0411-4f24-a81a-8a591c9bce6d")
        )
        user = uresult.unique().scalar_one()

        # Role-level only
        role_perms = (await session.execute(
            select(Permission.permission_name)
            .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
            .where(RolePermission.role_id == user.role_id)
        )).scalars().all()
        print("Staff ROLE-level grants include reply_external:", "communication:reply_external" in role_perms)
        print("Staff ROLE-level grants include ticket:reply:", "ticket:reply" in role_perms)

        # Effective (role + overrides)
        resolver = PermissionResolverService(
            role_permission_repository=RolePermissionRepository(session),
            permission_override_repository=PermissionOverrideRepository(session),
        )
        perms, overrides, scoped = await resolver.get_effective_permissions(user)
        print("\nEffective permissions (role+overrides), count:", len(perms))
        print("has communication:reply_external:", "communication:reply_external" in perms)
        print("has ticket:reply:", "ticket:reply" in perms)
        print("has ticket:update_status:", "ticket:update_status" in perms)
        print("\npermission_version:", user.permission_version)
    await engine.dispose()

asyncio.run(main())

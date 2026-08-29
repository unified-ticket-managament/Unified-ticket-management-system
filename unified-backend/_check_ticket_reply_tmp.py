import asyncio
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import User, Role
from app.database.session import AsyncSessionLocal, engine
from app.rbac.models.permission import Permission
from app.rbac.models.role_permission import RolePermission

async def main():
    async with AsyncSessionLocal() as session:
        # Does the Staff role hold ticket:reply in the live DB right now?
        result = await session.execute(
            select(Permission.permission_name)
            .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
            .join(Role, Role.role_id == RolePermission.role_id)
            .where(Role.name == "Staff")
            .order_by(Permission.permission_name)
        )
        staff_perms = [r[0] for r in result.fetchall()]
        print("Staff role currently holds ticket:reply:", "ticket:reply" in staff_perms)
        print("Staff role currently holds ticket:update_status:", "ticket:update_status" in staff_perms)
        print("Total Staff role permissions:", len(staff_perms))

        # Does the permission even exist in the catalog at all?
        result2 = await session.execute(
            select(Permission).where(Permission.permission_name == "ticket:reply")
        )
        perm_row = result2.scalar_one_or_none()
        print("ticket:reply exists in permissions catalog:", perm_row is not None)
    await engine.dispose()

asyncio.run(main())

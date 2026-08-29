import asyncio
from sqlalchemy import select
from shared_models.models import Role
from app.database.session import AsyncSessionLocal, engine
from app.rbac.models.permission import Permission
from app.rbac.models.role_permission import RolePermission
from scripts.rbac_seed.seed import DEFAULT_ROLES, REVOKED_GRANTS, DEPRECATED_PERMISSIONS

async def main():
    declared = set(DEFAULT_ROLES["Staff"])
    revoked_for_staff = {p for (r, p) in REVOKED_GRANTS if r == "Staff"}
    deprecated = set(DEPRECATED_PERMISSIONS)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Permission.permission_name)
            .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
            .join(Role, Role.role_id == RolePermission.role_id)
            .where(Role.name == "Staff")
        )
        live = set(r[0] for r in result.fetchall())

        missing = declared - live
        missing -= revoked_for_staff  # shouldn't overlap given seed.py's own invariant, but double-check
        missing -= deprecated

        print(f"Staff declared defaults: {len(declared)}")
        print(f"Staff live grants: {len(live)}")
        print(f"Missing (should be added): {sorted(missing)}")

        extra = live - declared
        print(f"\nLive but not in declared defaults (informational only, NOT touching): {sorted(extra)}")
    await engine.dispose()

asyncio.run(main())

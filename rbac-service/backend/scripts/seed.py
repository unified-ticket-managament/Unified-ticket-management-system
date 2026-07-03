import asyncio

from sqlalchemy import select

from app.auth.password import get_password_hash
from app.database.session import AsyncSessionLocal, engine
from app.models import Base, Permission, Role, RolePermission, User

DEFAULT_PERMISSIONS = [
    ("user:create", "Create users"),
    ("user:view", "View users"),
    ("user:update", "Update users"),
    ("user:delete", "Delete users"),
    ("role:create", "Create roles"),
    ("role:view", "View roles"),
    ("role:update", "Update roles"),
    ("role:delete", "Delete roles"),
    ("permission:view", "View permissions"),
    ("permission:update", "Update role permissions"),
    ("audit:view", "View audit logs"),
]

DEFAULT_ROLES = {
    "Super Admin": "all",
    "Manager": ["user:view", "user:create", "user:update", "role:view"],
    "Team Lead": ["user:view", "user:update", "role:view"],
    "Staff": ["user:view"],
    "Viewer": ["user:view", "role:view", "permission:view"],
}

DEMO_USERS = [
    {
        "name": "Super Admin",
        "email": "admin@rbac.com",
        "password": "Admin@123456",
        "role": "Super Admin",
    },
    {
        "name": "Manager",
        "email": "manager@probeps.com",
        "password": "Manager@123",
        "role": "Manager",
    },
    {
        "name": "Team Lead",
        "email": "teamlead@probeps.com",
        "password": "TeamLead@123",
        "role": "Team Lead",
        "manager_email": "manager@probeps.com",
    },
    {
        "name": "Priya Nair",
        "email": "priya.nair@probeps.com",
        "password": "Welcome@123",
        "role": "Team Lead",
        "manager_email": "manager@probeps.com",
    },
    {
        "name": "Staff",
        "email": "staff@probeps.com",
        "password": "Staff@123",
        "role": "Staff",
        "manager_email": "manager@probeps.com",
        "teamlead_email": "teamlead@probeps.com",
    },
    {
        "name": "John Carter",
        "email": "john.carter@probeps.com",
        "password": "Welcome@123",
        "role": "Staff",
        "manager_email": "manager@probeps.com",
        "teamlead_email": "teamlead@probeps.com",
    },
    {
        "name": "Emma Watts",
        "email": "emma.watts@probeps.com",
        "password": "Welcome@123",
        "role": "Staff",
        "manager_email": "manager@probeps.com",
        "teamlead_email": "priya.nair@probeps.com",
    },
    {
        "name": "Liam Brooks",
        "email": "liam.brooks@probeps.com",
        "password": "Welcome@123",
        "role": "Staff",
        "manager_email": "manager@probeps.com",
        "teamlead_email": "priya.nair@probeps.com",
    },
    {
        "name": "Viewer",
        "email": "viewer@probeps.com",
        "password": "Viewer@123",
        "role": "Viewer",
    },
    {
        "name": "Sophia Turner",
        "email": "sophia.turner@probeps.com",
        "password": "Welcome@123",
        "role": "Viewer",
    },
]

# Emails used by an earlier seed run that email-validator rejects
# (reserved/special-use TLDs). Renamed in place if found.
LEGACY_EMAIL_FIXES = {
    "admin@rbac.local": "admin@rbac.com",
}


async def seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:

        # --------------------------------------------------
        # Permissions (idempotent)
        # --------------------------------------------------

        permissions: dict[str, Permission] = {}

        for name, description in DEFAULT_PERMISSIONS:
            result = await session.execute(
                select(Permission).where(Permission.permission_name == name)
            )
            permission = result.scalar_one_or_none()

            if permission is None:
                permission = Permission(permission_name=name, description=description)
                session.add(permission)
                await session.flush()

            permissions[name] = permission

        # --------------------------------------------------
        # Roles (idempotent)
        # --------------------------------------------------

        roles: dict[str, Role] = {}

        for role_name in DEFAULT_ROLES:
            result = await session.execute(
                select(Role).where(Role.name == role_name)
            )
            role = result.scalar_one_or_none()

            if role is None:
                role = Role(name=role_name)
                session.add(role)
                await session.flush()

            roles[role_name] = role

        # --------------------------------------------------
        # Role -> Permission mappings (idempotent)
        # --------------------------------------------------

        for role_name, perm_names in DEFAULT_ROLES.items():
            role = roles[role_name]

            names = (
                list(permissions.keys())
                if perm_names == "all"
                else perm_names
            )

            existing = await session.execute(
                select(RolePermission.permission_id).where(
                    RolePermission.role_id == role.role_id
                )
            )
            existing_ids = {row[0] for row in existing.all()}

            for perm_name in names:
                permission = permissions[perm_name]

                if permission.permission_id not in existing_ids:
                    session.add(
                        RolePermission(
                            role_id=role.role_id,
                            permission_id=permission.permission_id,
                        )
                    )

        # --------------------------------------------------
        # Fix emails from an earlier seed run rejected by
        # email-validator (reserved/special-use TLDs)
        # --------------------------------------------------

        for old_email, new_email in LEGACY_EMAIL_FIXES.items():
            result = await session.execute(
                select(User).where(User.email == old_email)
            )
            legacy_user = result.scalar_one_or_none()

            if legacy_user is not None:
                legacy_user.email = new_email

        await session.flush()

        # --------------------------------------------------
        # Demo users (idempotent)
        # --------------------------------------------------

        users_by_email: dict[str, User] = {}

        for demo in DEMO_USERS:
            result = await session.execute(
                select(User).where(User.email == demo["email"])
            )
            user = result.scalar_one_or_none()

            if user is None:
                user = User(
                    name=demo["name"],
                    email=demo["email"],
                    password_hash=get_password_hash(demo["password"]),
                    role_id=roles[demo["role"]].role_id,
                    is_active=True,
                )
                session.add(user)
                await session.flush()

            users_by_email[demo["email"]] = user

        # Backfill manager/team-lead reporting lines wherever they're
        # still unset. Never overwrites an existing assignment, so
        # this is safe to re-run even if a user's links were changed
        # by hand afterwards.
        for demo in DEMO_USERS:
            user = users_by_email[demo["email"]]

            manager_email = demo.get("manager_email")
            if manager_email and user.manager_id is None:
                user.manager_id = users_by_email[manager_email].user_id

            teamlead_email = demo.get("teamlead_email")
            if teamlead_email and user.teamlead_id is None:
                user.teamlead_id = users_by_email[teamlead_email].user_id

        await session.commit()

        print("Seed completed.")
        for demo in DEMO_USERS:
            print(f"{demo['role']} login: {demo['email']} / {demo['password']}")


if __name__ == "__main__":
    asyncio.run(seed())

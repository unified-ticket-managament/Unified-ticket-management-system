import asyncio

from sqlalchemy import select

from app.core.security import get_password_hash
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
    "Super Admin": {
        "description": "Full system access",
        "permissions": "all",
    },
    "Manager": {
        "description": "Manage users under supervision",
        "permissions": ["user:view", "user:create", "user:update", "role:view"],
    },
    "Team Lead": {
        "description": "Manage team operations",
        "permissions": ["user:view", "user:update", "role:view"],
    },
    "Staff": {
        "description": "Access permitted features",
        "permissions": ["user:view"],
    },
    "Viewer": {
        "description": "Read-only access",
        "permissions": ["user:view", "role:view", "permission:view"],
    },
}

SUPER_ADMIN_EMAIL = "admin@rbac.local"
SUPER_ADMIN_PASSWORD = "Admin@123456"
SUPER_ADMIN_NAME = "Super Admin"


async def seed() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(Permission).limit(1))
        if existing.scalar_one_or_none():
            print("Database already seeded.")
            return

        permissions: dict[str, Permission] = {}
        for name, description in DEFAULT_PERMISSIONS:
            permission = Permission(permission_name=name, description=description)
            session.add(permission)
            permissions[name] = permission
        await session.flush()

        roles: dict[str, Role] = {}
        for role_name, config in DEFAULT_ROLES.items():
            role = Role(name=role_name, description=config["description"])
            session.add(role)
            roles[role_name] = role
        await session.flush()

        for role_name, config in DEFAULT_ROLES.items():
            role = roles[role_name]
            perm_names = (
                list(permissions.keys())
                if config["permissions"] == "all"
                else config["permissions"]
            )
            for perm_name in perm_names:
                session.add(
                    RolePermission(role_id=role.id, permission_id=permissions[perm_name].id)
                )

        admin = User(
            name=SUPER_ADMIN_NAME,
            email=SUPER_ADMIN_EMAIL,
            password_hash=get_password_hash(SUPER_ADMIN_PASSWORD),
            role_id=roles["Super Admin"].id,
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        print("Seed completed.")
        print(f"Super Admin login: {SUPER_ADMIN_EMAIL} / {SUPER_ADMIN_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())

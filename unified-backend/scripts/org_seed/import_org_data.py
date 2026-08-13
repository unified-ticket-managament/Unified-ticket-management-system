# import_org_data.py
#
# The real write. Run ONLY after:
#   1. `alembic -c alembic_rbac/alembic.ini upgrade head`
#   2. `alembic -c alembic_ticketing/alembic.ini upgrade head`
#   3. `python -m scripts.org_seed.validate` reports zero errors and
#      you've reviewed the warnings.
#
# Wipes users/roles and everything that cascades from them (clients,
# tickets, interactions, permission tables, reporting_manager_teams,
# client_assignments, client_contacts, audit logs — anything with an FK
# reaching back to users or roles), then re-seeds permissions/roles
# from scratch and writes the real org's users/clients/client
# ownership/client contacts on top. `categories` is deliberately NOT
# touched here — the d3f5a7b9c1e3 migration already replaced its rows
# with the real 8 category names; this script only reads them.
#
# Usage (from unified-backend/, with the venv active):
#   python -m scripts.org_seed.import_org_data

import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import asyncio  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.auth.password import get_password_hash  # noqa: E402
from app.database.session import AsyncSessionLocal, engine  # noqa: E402
from app.rbac.models import Base, Category, Permission, Role, RolePermission, User  # noqa: E402
from app.ticketing.models import Client, ClientAssignment, ClientContact  # noqa: E402
from scripts.org_seed import mapping  # noqa: E402
from scripts.org_seed.build import build  # noqa: E402
from scripts.rbac_seed.seed import DEFAULT_PERMISSIONS, DEFAULT_ROLES  # noqa: E402

# Written OUTSIDE the repo (scratchpad), never committed — plaintext
# temp credentials for one-time handoff. Delete this file yourself
# once you've distributed the passwords.
CREDENTIALS_OUTPUT_FILE = Path(
    r"C:\Users\javva\AppData\Local\Temp\claude\c--Users-javva-Deployment-UTMS\6b6bdba1-4323-4a8e-a3f6-ac6578a4a1ab\scratchpad\org_seed_credentials.txt"
)


def generate_temp_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "Pb-" + "".join(secrets.choice(alphabet) for _ in range(10)) + "!1"


async def wipe_existing_data(session) -> None:
    await session.execute(text("TRUNCATE TABLE users, roles CASCADE"))
    await session.commit()


async def seed_permissions_and_roles(session) -> dict[str, Role]:
    permissions: dict[str, Permission] = {}
    for name, description in DEFAULT_PERMISSIONS:
        existing = (
            await session.execute(select(Permission).where(Permission.permission_name == name))
        ).scalar_one_or_none()
        if existing is None:
            existing = Permission(permission_name=name, description=description)
            session.add(existing)
            await session.flush()
        permissions[name] = existing

    roles: dict[str, Role] = {}
    for role_name in DEFAULT_ROLES:
        existing = (
            await session.execute(select(Role).where(Role.name == role_name))
        ).scalar_one_or_none()
        if existing is None:
            existing = Role(name=role_name)
            session.add(existing)
            await session.flush()
        roles[role_name] = existing

    for role_name, perm_names in DEFAULT_ROLES.items():
        role = roles[role_name]
        names = list(permissions.keys()) if perm_names == "all" else perm_names
        existing_grant_ids = {
            row[0]
            for row in (
                await session.execute(
                    select(RolePermission.permission_id).where(RolePermission.role_id == role.role_id)
                )
            ).all()
        }
        for perm_name in names:
            permission = permissions[perm_name]
            if permission.permission_id not in existing_grant_ids:
                session.add(RolePermission(role_id=role.role_id, permission_id=permission.permission_id))

    await session.commit()
    return roles


async def main() -> None:
    result = build()
    if any(issue.severity == "error" for issue in result.issues):
        print(
            "Validation errors present - run `python -m scripts.org_seed.validate` "
            "and resolve them first. Aborting without touching the database."
        )
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        print("Wiping existing users/roles (and everything that cascades from them)...")
        await wipe_existing_data(session)

        print("Seeding permissions + roles...")
        roles = await seed_permissions_and_roles(session)

        categories_by_name: dict[str, Category] = {
            category.category_name.value: category
            for category in (await session.execute(select(Category))).scalars().all()
        }
        missing_categories = set(mapping.NEW_CATEGORY_NAMES) - set(categories_by_name)
        if missing_categories:
            print(
                f"Warning: categories table is missing {sorted(missing_categories)} — "
                "run `alembic -c alembic_rbac/alembic.ini upgrade head` first."
            )

        # ------------------------------------------------------------
        # Users: pass 1 (create, no manager_id/teamlead_id/category_id yet)
        # ------------------------------------------------------------

        print(f"Seeding {len(result.employees)} users...")
        credentials: list[tuple[str, str, str]] = []  # (email, role, password)
        users_by_employee_id: dict[int, User] = {}

        for emp in result.employees.values():
            existing = (
                await session.execute(select(User).where(User.email == emp.email))
            ).scalar_one_or_none()

            if existing is None:
                password = generate_temp_password()
                existing = User(
                    name=emp.name,
                    email=emp.email,
                    password_hash=get_password_hash(password),
                    role_id=roles[emp.role].role_id,
                    designation=emp.designation,
                    is_active=True,
                )
                session.add(existing)
                await session.flush()
                credentials.append((emp.email, emp.role, password))

            users_by_employee_id[emp.employee_id] = existing

        await session.flush()

        # ------------------------------------------------------------
        # Users: pass 2 (manager_id / teamlead_id / category_id)
        # ------------------------------------------------------------

        for emp in result.employees.values():
            user = users_by_employee_id[emp.employee_id]

            user.manager_id = (
                users_by_employee_id[emp.manager_employee_id].user_id
                if emp.manager_employee_id is not None
                else None
            )
            user.teamlead_id = (
                users_by_employee_id[emp.teamlead_employee_id].user_id
                if emp.teamlead_employee_id is not None
                else None
            )
            user.category_id = (
                categories_by_name[emp.category].category_id
                if emp.category is not None and emp.category in categories_by_name
                else None
            )

        await session.commit()

        # ------------------------------------------------------------
        # Clients + client_assignments + client_contacts
        # ------------------------------------------------------------

        print(f"Seeding {len(result.clients)} clients...")
        clients_by_name: dict[str, Client] = {}

        for client_rec in result.clients.values():
            # Matched by name, not inbox_email — several clients can
            # legitimately share a NULL inbox_email (no configured
            # distribution address), which inbox_email could never
            # have disambiguated between anyway.
            existing = (
                await session.execute(select(Client).where(Client.name == client_rec.name))
            ).scalar_one_or_none()

            if existing is None:
                existing = Client(
                    name=client_rec.name,
                    inbox_email=client_rec.inbox_email,
                    account_manager_id=users_by_employee_id[client_rec.account_manager_employee_id].user_id,
                )
                session.add(existing)
                await session.flush()

            clients_by_name[client_rec.name] = existing

        await session.commit()

        print("Seeding client_assignments...")
        for client_rec in result.clients.values():
            client = clients_by_name[client_rec.name]
            for assignment in client_rec.lead_assignments:
                existing = (
                    await session.execute(
                        select(ClientAssignment).where(
                            ClientAssignment.client_id == client.client_id,
                            ClientAssignment.lead_role == assignment.lead_role,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.add(
                        ClientAssignment(
                            client_id=client.client_id,
                            lead_role=assignment.lead_role,
                            user_id=users_by_employee_id[assignment.employee_id].user_id,
                        )
                    )

        await session.commit()

        print("Seeding client_contacts...")
        for client_rec in result.clients.values():
            client = clients_by_name[client_rec.name]
            for email in client_rec.contact_emails:
                existing = (
                    await session.execute(
                        select(ClientContact).where(
                            ClientContact.client_id == client.client_id,
                            ClientContact.email == email,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    # No contact is ever marked primary by this
                    # import anymore — "primary" used to mean
                    # "promoted to inbox_email", a concept that no
                    # longer exists now that inbox_email is a
                    # curated, explicit distribution address (see
                    # mapping.resolve_distribution_email).
                    session.add(
                        ClientContact(
                            client_id=client.client_id,
                            email=email,
                            is_primary=False,
                        )
                    )

        await session.commit()

    if credentials:
        CREDENTIALS_OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CREDENTIALS_OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write("email,role,temporary_password\n")
            for email, role, password in credentials:
                f.write(f"{email},{role},{password}\n")
        print(
            f"\n{len(credentials)} new user(s) created. Temporary passwords written to:\n"
            f"  {CREDENTIALS_OUTPUT_FILE}\n"
            "Distribute these out-of-band and delete that file once you're done — it is "
            "NOT written inside the git repo and must not be committed anywhere."
        )
    else:
        print("\nNo new users created (all emails already existed).")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())

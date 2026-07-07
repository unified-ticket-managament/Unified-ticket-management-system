# seed_clients.py
#
# Day-1 demo data: onboards a few client companies against real
# active Account Manager-role users from the shared `users` table,
# so the AM-routing pipeline has something to resolve against.
# Idempotent — safe to re-run; existing inbox_email rows are left
# untouched.
#
# Usage (from backend/, with the venv active):
#   python scripts/seed_clients.py

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.session import AsyncSessionLocal  # noqa: E402
from app.repositories.client_repository import ClientRepository  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402
from app.schemas.client import ClientCreate  # noqa: E402
from app.services.access_control import ACCOUNT_MANAGER_ROLE_NAME  # noqa: E402

DEMO_CLIENTS = [
    {"name": "ABC Clinic", "inbox_email": "abc@probeps.com"},
    {"name": "XYZ Medical Group", "inbox_email": "xyz@probeps.com"},
    {"name": "Sunrise Health", "inbox_email": "sunrise@probeps.com"},
]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        user_repository = UserRepository(db)
        client_repository = ClientRepository(db)

        managers = await user_repository.list_active_by_role_name(
            ACCOUNT_MANAGER_ROLE_NAME
        )

        if not managers:
            print(
                "No active Account Manager-role users found in the shared `users` "
                "table — seed at least one Account Manager in the RBAC service first."
            )
            return

        created = 0
        for i, demo in enumerate(DEMO_CLIENTS):
            existing = await client_repository.get_by_inbox_email(demo["inbox_email"])
            if existing is not None:
                print(f"skip  {demo['inbox_email']} (already exists)")
                continue

            manager = managers[i % len(managers)]
            client = await client_repository.create(
                ClientCreate(
                    name=demo["name"],
                    inbox_email=demo["inbox_email"],
                    account_manager_id=manager.user_id,
                )
            )
            created += 1
            print(f"created {client.inbox_email} -> {demo['name']} (AM: {manager.name})")

        await db.commit()
        print(f"\nDone. {created} client(s) created.")


if __name__ == "__main__":
    asyncio.run(main())

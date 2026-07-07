# seed_clients.py
#
# Day-1 demo data: onboards client companies against real active
# Account Manager-role users from the shared `users` table, each with
# an explicit, deterministic `manager_email` — no round-robin. If a
# client's mapped email doesn't resolve to an active Account Manager,
# that one client is skipped with a warning; the rest of the run
# still proceeds.
# Idempotent — safe to re-run; existing inbox_email rows are left
# untouched (their account_manager_id is never reassigned by a later
# run, even if this list's mapping for that email changes).
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

# manager_email defaults to manager@probeps.com — the one Account
# Manager guaranteed to exist from rbac-service's own seed data.
# Don't point new entries at ad hoc, manually-created accounts (e.g.
# one made through the Users UI) — they won't exist on a fresh DB.
DEMO_CLIENTS = [
    {"name": "ABC Clinic", "inbox_email": "abc@probeps.com", "manager_email": "manager@probeps.com"},
    {"name": "XYZ Medical Group", "inbox_email": "xyz@probeps.com", "manager_email": "manager@probeps.com"},
    {"name": "Sunrise Health", "inbox_email": "sunrise@probeps.com", "manager_email": "manager@probeps.com"},
    {"name": "Lakeside Pediatrics", "inbox_email": "lakeside@probeps.com", "manager_email": "manager@probeps.com"},
    {"name": "Metro Family Care", "inbox_email": "metro@probeps.com", "manager_email": "manager@probeps.com"},
    {"name": "Golden State Orthopedics", "inbox_email": "goldenstate@probeps.com", "manager_email": "manager@probeps.com"},
    {"name": "Riverbend Dental Group", "inbox_email": "riverbend@probeps.com", "manager_email": "manager@probeps.com"},
]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        user_repository = UserRepository(db)
        client_repository = ClientRepository(db)

        created = 0
        skipped_existing = 0
        skipped_bad_manager = 0

        for demo in DEMO_CLIENTS:
            existing = await client_repository.get_by_inbox_email(demo["inbox_email"])
            if existing is not None:
                print(f"skip  {demo['inbox_email']} (already exists)")
                skipped_existing += 1
                continue

            manager = await user_repository.get_by_email(demo["manager_email"])
            if (
                manager is None
                or not manager.is_active
                or manager.role.name != ACCOUNT_MANAGER_ROLE_NAME
            ):
                print(
                    f"skip  {demo['inbox_email']} — {demo['manager_email']} is not an "
                    "active Account Manager (seed that user in rbac-service first)"
                )
                skipped_bad_manager += 1
                continue

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
        print(
            f"\nDone. {created} created, {skipped_existing} already existed, "
            f"{skipped_bad_manager} skipped (no valid Account Manager)."
        )


if __name__ == "__main__":
    asyncio.run(main())

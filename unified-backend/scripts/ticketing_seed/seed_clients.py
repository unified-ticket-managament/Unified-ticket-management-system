# seed_clients.py
#
# Day-1 demo data: onboards client companies against real active
# Account Manager-role users from the shared `users` table.
#
# Routing is 1:1 per client, never round-robin at RUNTIME — that
# invariant is unchanged. But this script previously hardcoded every
# demo client's `manager_email` to the same "manager@probeps.com",
# which meant every client routed to one Account Manager regardless
# of how many real AM accounts existed — indistinguishable from a
# genuine routing bug when viewed from the Mail inbox. Fixed by
# discovering every currently-active Account Manager and assigning
# each demo client to one, deterministically, by list position
# (client[i] -> AMs[i % len(AMs)]) — computed once at seed time, not
# a repeated runtime policy. On a fresh DB with only the one
# guaranteed "manager@probeps.com" account, every client still maps
# to that single AM (there's genuinely only one to route to — not a
# bug). Create a second Account Manager via RBAC's Users admin page
# (or its own seed script) before running this to see clients split
# across multiple AMs.
#
# Idempotent — safe to re-run; existing inbox_email rows are left
# untouched (their account_manager_id is never reassigned by a later
# run, even if this run would have picked a different AM for it).
#
# Usage (from backend/, with the venv active):
#   python scripts/seed_clients.py

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.database.session import AsyncSessionLocal  # noqa: E402
from app.ticketing.repositories.client_repository import ClientRepository  # noqa: E402
from app.ticketing.repositories.user_repository import UserRepository  # noqa: E402
from app.ticketing.schemas.client import ClientCreate  # noqa: E402
from app.ticketing.services.access_control import ACCOUNT_MANAGER_ROLE_NAME  # noqa: E402

DEMO_CLIENTS = [
    # These four were switched from dummy @probeps.com placeholders
    # (abc@, xyz@, sunrise@, riverbend@) to real, reachable internal
    # mailboxes once Graph deliverability to external addresses proved
    # unreliable — see M365_OUTBOUND_DELIVERY_ISSUE.md. Inbound/outbound
    # between probeps.com and painmedpa.com is confirmed working, so
    # these are usable for genuine end-to-end mail testing today.
    # Lakeside Pediatrics stays on its original dummy address.
    {"name": "ABC Clinic", "inbox_email": "deva@painmedpa.com"},
    {"name": "XYZ Medical Group", "inbox_email": "shreyojit@probeps.com"},
    {"name": "Sunrise Health", "inbox_email": "revanth@probeps.com"},
    {"name": "Lakeside Pediatrics", "inbox_email": "lakeside@probeps.com"},
    {"name": "Metro Family Care", "inbox_email": "metro@probeps.com"},
    {"name": "Golden State Orthopedics", "inbox_email": "goldenstate@probeps.com"},
    {"name": "Riverbend Dental Group", "inbox_email": "gogineni@painmedpa.com"},
]


async def main() -> None:
    async with AsyncSessionLocal() as db:
        user_repository = UserRepository(db)
        client_repository = ClientRepository(db)

        account_managers = await user_repository.list_active_by_role_name(
            ACCOUNT_MANAGER_ROLE_NAME
        )

        if not account_managers:
            print(
                "No active Account Manager found — seed one in rbac-service "
                "first (its own seed.py creates manager@probeps.com)."
            )
            return

        print(
            f"Distributing {len(DEMO_CLIENTS)} demo clients across "
            f"{len(account_managers)} active Account Manager(s): "
            + ", ".join(am.email for am in account_managers)
        )

        created = 0
        skipped_existing = 0

        for index, demo in enumerate(DEMO_CLIENTS):
            existing = await client_repository.get_by_inbox_email(demo["inbox_email"])
            if existing is not None:
                print(f"skip  {demo['inbox_email']} (already exists)")
                skipped_existing += 1
                continue

            manager = account_managers[index % len(account_managers)]

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
        print(f"\nDone. {created} created, {skipped_existing} already existed.")


if __name__ == "__main__":
    asyncio.run(main())

# remove_test_clients.py
#
# One-time cleanup: removes the 6 leftover "Live Escalation Test
# Client" rows (and everything that references them) left behind by an
# earlier live-testing session against this shared dev database. Scoped
# to these exact client_ids, not a name/email LIKE pattern, so it can
# never accidentally catch a real client.
#
# Deletes in FK-dependency order: notifications -> ticket_audit_logs ->
# ticket_escalations -> resolution_slas -> tickets -> clients.
#
# Usage (from unified-backend/, with the venv active):
#   python -m scripts.remove_test_clients

import asyncio

from sqlalchemy import text

from app.database.session import AsyncSessionLocal

CLIENT_IDS = [
    "1802014b-28cf-461f-a2ee-4d1d6531282c",
    "d63c0bf2-37cf-4bd6-9f1c-4fd8481eee01",
    "cac84215-6406-463d-a917-9e0c4d3311dc",
    "e3005153-807d-4d9f-b88d-7f0be3eac2e1",
    "aedfca50-3878-4f20-8bba-0e0ff1da330e",
    "ccc73e8d-dda7-452d-b624-188bc62c51d3",
]


async def main() -> None:
    async with AsyncSessionLocal() as session:
        ticket_ids = (
            await session.execute(
                text("SELECT ticket_id FROM tickets WHERE client_company_id = ANY(:ids)"),
                {"ids": CLIENT_IDS},
            )
        ).scalars().all()
        ticket_ids = [str(t) for t in ticket_ids]
        print(f"Found {len(ticket_ids)} ticket(s) under these {len(CLIENT_IDS)} client(s).")

        if ticket_ids:
            n = await session.execute(
                text("DELETE FROM notifications WHERE related_entity_id = ANY(:ids)"), {"ids": ticket_ids}
            )
            print(f"Deleted {n.rowcount} notification row(s).")

            n = await session.execute(
                text("DELETE FROM ticket_audit_logs WHERE ticket_id = ANY(:ids)"), {"ids": ticket_ids}
            )
            print(f"Deleted {n.rowcount} ticket_audit_logs row(s).")

            n = await session.execute(
                text("DELETE FROM ticket_escalations WHERE ticket_id = ANY(:ids)"), {"ids": ticket_ids}
            )
            print(f"Deleted {n.rowcount} ticket_escalations row(s).")

            n = await session.execute(
                text("DELETE FROM resolution_slas WHERE ticket_id = ANY(:ids)"), {"ids": ticket_ids}
            )
            print(f"Deleted {n.rowcount} resolution_slas row(s).")

            n = await session.execute(text("DELETE FROM tickets WHERE ticket_id = ANY(:ids)"), {"ids": ticket_ids})
            print(f"Deleted {n.rowcount} ticket row(s).")

        n = await session.execute(text("DELETE FROM clients WHERE client_id = ANY(:ids)"), {"ids": CLIENT_IDS})
        print(f"Deleted {n.rowcount} client row(s).")

        await session.commit()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())

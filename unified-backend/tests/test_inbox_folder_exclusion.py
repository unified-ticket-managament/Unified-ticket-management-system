# test_inbox_folder_exclusion.py
#
# DB-required regression coverage for: a Rule's move_to_folder action
# (or a manual PATCH /inbox/{id}/folder) sets Interaction.folder_id but
# never touched `status`/`ticket_id`, so the item kept satisfying the
# "pending" (Inbox) view's query exactly as if it had never been filed
# — the item stayed in Inbox forever alongside also being reachable via
# the folder. Fixed by adding `folder_id IS NULL` to list_inbox's/
# count_by_view's "pending" branch only; every other view (all/
# ticketed/archived/replied) and folder_id-scoped queries are
# deliberately untouched. Same real-DB-inside-a-rolled-back-transaction
# convention as test_folder_sharing_visibility.py.

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus, TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_super_admin(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Super Admin", User.is_active.is_(True))
    )
    admin = result.unique().scalars().first()
    if admin is None:
        pytest.skip("No active seeded Super Admin found to use as folder creator.")
    return admin


async def _make_client(session, *, account_manager_id) -> Client:
    client = Client(
        client_id=uuid.uuid4(),
        name="Inbox Folder Exclusion Test Client",
        inbox_email=f"inbox-folder-exclusion-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()
    return client


async def _make_email(
    session,
    *,
    client_id,
    folder_id=None,
    ticket_id=None,
    status=InteractionStatus.PENDING,
    subject="Test",
) -> Interaction:
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        status=status,
        payload={
            "subject": subject,
            "body": "Test body",
            "from_email": "client@example.com",
            "to_email": "support@probeps.com",
            "client_name": "Inbox Folder Exclusion Test Client",
        },
        parent_interaction_id=None,
        ticket_id=ticket_id,
        client_id=client_id,
        folder_id=folder_id,
        is_visible=True,
        subject=subject,
        received_at=datetime.now(timezone.utc),
    )
    session.add(interaction)
    await session.flush()
    return interaction


async def _make_ticket(session, *, client_id, ticket_type: str) -> Ticket:
    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client_id,
        title="Inbox Folder Exclusion Test Ticket",
        ticket_type=ticket_type,
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        custom_fields={},
    )
    session.add(ticket)
    await session.flush()
    return ticket


async def test_folder_filed_pending_item_excluded_from_pending_view_but_reachable_elsewhere(
    db_session,
):
    admin = await _get_super_admin(db_session)
    client = await _make_client(db_session, account_manager_id=admin.user_id)

    folder_repository = MailFolderRepository(db_session)
    folder = await folder_repository.create(
        f"Inbox Exclusion Test Folder {uuid.uuid4().hex[:8]}", created_by=admin.user_id
    )

    unfiled_email = await _make_email(db_session, client_id=client.client_id, folder_id=None)
    filed_email = await _make_email(
        db_session, client_id=client.client_id, folder_id=folder.folder_id
    )

    repo = InteractionRepository(db_session)

    # --- "pending" (Inbox): the filed item must no longer appear, the
    # unfiled one must be unaffected. Super Admin is globally unscoped
    # (no account_manager_id/ticket_types/assigned_agent_id), so any
    # difference here can only come from the folder_id filter itself. ---
    pending_items, pending_total = await repo.list_inbox(view="pending")
    pending_ids = {item.interaction_id for item in pending_items}
    assert unfiled_email.interaction_id in pending_ids
    assert filed_email.interaction_id not in pending_ids

    # --- "all": both rows remain visible — filing something into a
    # folder must never make it disappear from the system entirely. ---
    all_items, _ = await repo.list_inbox(view="all")
    all_ids = {item.interaction_id for item in all_items}
    assert unfiled_email.interaction_id in all_ids
    assert filed_email.interaction_id in all_ids

    # --- folder_id-scoped query: the filed item is still reachable
    # through its folder, exactly as the requirement asks for. ---
    folder_items, _ = await repo.list_inbox(view="all", folder_id=folder.folder_id)
    folder_ids = {item.interaction_id for item in folder_items}
    assert filed_email.interaction_id in folder_ids
    assert unfiled_email.interaction_id not in folder_ids

    # --- count_by_view's "pending" count must agree with the list
    # above (list/badge-count drift would be its own bug). ---
    counts = await repo.count_by_view()
    assert counts["pending"] == pending_total


async def test_ticketed_item_with_folder_id_still_appears_under_ticketed_view(db_session):
    # Regression guard: the "ticketed" view branch is deliberately
    # untouched by this fix — once an interaction is attached to a
    # ticket, folder tagging must not hide it from the Ticketed tab.
    admin = await _get_super_admin(db_session)
    client = await _make_client(db_session, account_manager_id=admin.user_id)

    folder_repository = MailFolderRepository(db_session)
    folder = await folder_repository.create(
        f"Inbox Exclusion Ticketed Test Folder {uuid.uuid4().hex[:8]}",
        created_by=admin.user_id,
    )

    ticket = await _make_ticket(db_session, client_id=client.client_id, ticket_type="AR")
    ticketed_and_filed_email = await _make_email(
        db_session,
        client_id=client.client_id,
        folder_id=folder.folder_id,
        ticket_id=ticket.ticket_id,
        status=InteractionStatus.ASSIGNED,
    )

    repo = InteractionRepository(db_session)

    ticketed_items, _ = await repo.list_inbox(view="ticketed")
    ticketed_ids = {item.interaction_id for item in ticketed_items}
    assert ticketed_and_filed_email.interaction_id in ticketed_ids

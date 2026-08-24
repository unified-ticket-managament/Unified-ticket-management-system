# test_folder_sharing_visibility.py
#
# DB-required regression coverage for the "Sharing shows 0 messages"
# bug: sharing a rule/folder with a Team Lead/Staff target only ever
# granted folder EXISTENCE (GET /folders), never message-level
# visibility (GET /inbox, GET /inbox/folder-counts) — a mandatory
# role-ownership INNER JOIN against `tickets` silently dropped any
# pre-ticket row (ticket_id IS NULL) before the folder_id filter was
# even evaluated, and a ticketed row whose ticket_type didn't match
# the viewer's own category was excluded the same way. Fixed by
# MailFolderService.resolve_folder_access + InboxService's
# bypass_ownership_scope/shared_folder_ids plumbing.
#
# This can't be faithfully faked (see the approved plan's own
# Verification section) — the bug is specifically about SQL JOIN-
# before-WHERE semantics, so it needs a real Postgres query. Runs
# against the real (dev) database inside a transaction that is always
# rolled back at the end — same convention as test_inbox_ticket_service.py
# / test_interaction_threading.py.

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
from app.ticketing.models.rule import Rule
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.services.inbox_service import InboxService
from app.ticketing.services.mail_folder_service import MailFolderService

TEAM_LEAD_CATEGORY = "Payment Posting"
OTHER_CATEGORY = "AR"
# The ticketed test row's own ticket_type — deliberately a THIRD
# category, distinct from both the shared-access Team Lead's own
# category and the unrelated viewer's, so a positive result for either
# viewer can only come from the folder-sharing bypass itself, never
# from their own unrelated normal category-ownership scope.
FOREIGN_TICKET_CATEGORY = "Referral"


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
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Super Admin", User.is_active.is_(True))
    )
    admin = result.scalars().first()
    if admin is None:
        pytest.skip("No active seeded Super Admin found to use as an unrelated rule/folder creator.")
    return admin


async def _get_team_lead(session, category_name: str) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role), joinedload(User.category), joinedload(User.categories))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Team Lead", User.is_active.is_(True))
    )
    for user in result.unique().scalars().all():
        if user.category is not None and user.category.category_name == category_name:
            return user
    pytest.skip(f"No active seeded Team Lead found for category {category_name!r}.")


async def _make_client(session, *, account_manager_id) -> Client:
    client = Client(
        client_id=uuid.uuid4(),
        name="Folder Sharing Test Client",
        inbox_email=f"folder-sharing-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()
    return client


async def _make_email(session, *, client_id, folder_id, ticket_id=None) -> Interaction:
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        status=InteractionStatus.PENDING,
        payload={
            "subject": "Test",
            "body": "Test body",
            "from_email": "client@example.com",
            "to_email": "support@probeps.com",
            "client_name": "Folder Sharing Test Client",
        },
        parent_interaction_id=None,
        ticket_id=ticket_id,
        client_id=client_id,
        folder_id=folder_id,
        is_visible=True,
        subject="Test",
        received_at=datetime.now(timezone.utc),
    )
    session.add(interaction)
    await session.flush()
    return interaction


async def _make_ticket(session, *, client_id, ticket_type: str) -> Ticket:
    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client_id,
        title="Folder Sharing Test Ticket",
        ticket_type=ticket_type,
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        custom_fields={},
    )
    session.add(ticket)
    await session.flush()
    return ticket


async def test_shared_folder_surfaces_messages_for_team_lead_but_not_unrelated_viewer(db_session):
    team_lead = await _get_team_lead(db_session, TEAM_LEAD_CATEGORY)
    unrelated_viewer = await _get_team_lead(db_session, OTHER_CATEGORY)
    if unrelated_viewer.user_id == team_lead.user_id:
        pytest.skip("Need two distinct Team Leads across different categories for this test.")
    team_lead.permissions = ["communication:view_assigned"]
    unrelated_viewer.permissions = ["communication:view_assigned"]

    admin = await _get_super_admin(db_session)
    client = await _make_client(
        db_session, account_manager_id=team_lead.manager_id or team_lead.user_id
    )

    folder_repository = MailFolderRepository(db_session)
    folder = await folder_repository.create(
        f"Shared Test Folder {uuid.uuid4().hex[:8]}", created_by=admin.user_id
    )

    rule = Rule(
        rule_id=uuid.uuid4(),
        name="Test share rule",
        category="MAIL_RULE",
        is_enabled=True,
        conditions={"combinator": "AND", "rules": []},
        exceptions={"combinator": "AND", "rules": []},
        actions=[{"type": "move_to_folder", "folder_name": folder.name}],
        priority=1,
        created_by=admin.user_id,
        shared_user_ids=[str(team_lead.user_id)],
    )
    db_session.add(rule)
    await db_session.flush()

    # A pre-ticket row (ticket_id IS NULL) — the exact shape a Team
    # Lead/Staff's mandatory INNER JOIN against `tickets` used to drop
    # unconditionally, before folder_id was even evaluated.
    pre_ticket_email = await _make_email(
        db_session, client_id=client.client_id, folder_id=folder.folder_id
    )

    # A ticketed row whose ticket_type deliberately does NOT match the
    # Team Lead's own category — proves the fix isn't just "your own
    # category's tickets happened to already show up here".
    other_category_ticket = await _make_ticket(
        db_session, client_id=client.client_id, ticket_type=FOREIGN_TICKET_CATEGORY
    )
    ticketed_email = await _make_email(
        db_session,
        client_id=client.client_id,
        folder_id=folder.folder_id,
        ticket_id=other_category_ticket.ticket_id,
    )

    mail_folder_service = MailFolderService(folder_repository)
    rule_repository = RuleRepository(db_session)
    distribution_list_repository = DistributionListRepository(db_session)

    # --- Folder-existence access (rule sharing grant itself) ---
    shared_access = await mail_folder_service.resolve_folder_access(
        folder, team_lead, rule_repository, distribution_list_repository
    )
    assert shared_access.visible is True
    assert shared_access.via_sharing is True

    unrelated_access = await mail_folder_service.resolve_folder_access(
        folder, unrelated_viewer, rule_repository, distribution_list_repository
    )
    assert unrelated_access.visible is False
    assert unrelated_access.via_sharing is False

    inbox_service = InboxService(InteractionRepository(db_session))

    # --- Pre-fix behavior (no bypass): the shared folder's own
    # messages are still invisible to the Team Lead, matching the
    # originally reported bug exactly. ---
    without_bypass = await inbox_service.get_inbox(
        team_lead, view="all", folder_id=folder.folder_id, bypass_ownership_scope=False
    )
    assert without_bypass.total == 0

    # --- Post-fix behavior: bypass_ownership_scope=True (set only
    # after resolve_folder_access confirmed via_sharing) surfaces both
    # rows — the pre-ticket one AND the other-category ticketed one. ---
    with_bypass = await inbox_service.get_inbox(
        team_lead, view="all", folder_id=folder.folder_id, bypass_ownership_scope=True
    )
    assert with_bypass.total == 2
    returned_ids = {item.interaction_id for item in with_bypass.items}
    assert returned_ids == {pre_ticket_email.interaction_id, ticketed_email.interaction_id}

    # --- The unrelated viewer (not shared, not creator, no
    # rule:view_all) must never get this bypass at all — confirmed by
    # get_inbox with bypass_ownership_scope left False, the only value
    # any real route would ever pass for them (resolve_folder_access
    # already returned via_sharing=False above). ---
    unrelated_result = await inbox_service.get_inbox(
        unrelated_viewer, view="all", folder_id=folder.folder_id, bypass_ownership_scope=False
    )
    assert unrelated_result.total == 0

    # --- get_folder_counts: the two-query-merge shape. Without the
    # folder in shared_folder_ids, the count is the normally-scoped
    # (and here, zero) result; with it included, the real count. ---
    counts_without_sharing = await inbox_service.get_folder_counts(team_lead)
    assert counts_without_sharing.get(folder.folder_id, 0) == 0

    counts_with_sharing = await inbox_service.get_folder_counts(
        team_lead, shared_folder_ids={folder.folder_id}
    )
    assert counts_with_sharing.get(folder.folder_id) == 2

    # --- No regression: the Team Lead's own regular (non-folder-
    # scoped) inbox view is completely unaffected by any of the above
    # — it never receives the bypass, and neither test row belongs to
    # their own category/clients. ---
    own_scope_result = await inbox_service.get_inbox(team_lead, view="all")
    own_scope_ids = {item.interaction_id for item in own_scope_result.items}
    assert pre_ticket_email.interaction_id not in own_scope_ids
    assert ticketed_email.interaction_id not in own_scope_ids

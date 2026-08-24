# test_rule_delete_folder_cleanup.py
#
# Regression coverage for two related bugs in Mail Rule deletion:
#
# 1. (Original bug) Deleting a Mail/OTP Rule whose action files mail
#    into a folder that still holds real Interaction rows crashed with
#    an unhandled 500 (asyncpg.exceptions.ForeignKeyViolationError on
#    interactions_folder_id_fkey) — the browser reported this as a
#    CORS failure (no error-response CORS headers), masking the real
#    cause.
#
# 2. (This pass) The original fix for #1 was to simply leave the
#    folder in place forever whenever it still held messages — correct
#    for data safety, but wrong product behavior: the rule is gone,
#    yet its folder lingers indefinitely as an orphaned, rule-less
#    folder, and the routed emails never rejoin the normal Inbox. The
#    actual required behavior: delete a rule-EXCLUSIVELY-owned folder
#    unconditionally, but first clear folder_id (never delete the
#    interaction/ticket/attachment/audit data) so those emails become
#    ordinary Inbox items again.
#
# `MailFolder.is_rule_created` (set only by rule_folder_sync.ensure_folder,
# never by MailFolderService.create's manual POST /folders path) is the
# real ownership signal RuleService.delete's cleanup now uses — plain
# `created_by` can't tell a rule-created folder apart from a manually-
# created one, since both get a non-null created_by.
#
# Runs against the real (dev) database inside a transaction that is
# always rolled back at the end — same convention as
# test_inbox_ticket_service.py / test_folder_sharing_visibility.py.

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus, TicketPriority
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.schemas.rule import RuleActionItem, RuleConditionGroup, RuleCreate
from app.ticketing.services.rule_service import RuleService


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
        pytest.skip("No active seeded Super Admin found.")
    return admin


async def _make_client(session, *, account_manager_id) -> Client:
    client = Client(
        client_id=uuid.uuid4(),
        name="Rule Delete Test Client",
        inbox_email=f"rule-delete-test-{uuid.uuid4().hex[:8]}@example.com",
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
            "client_name": "Rule Delete Test Client",
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


async def _make_ticket(session, *, client_id) -> Ticket:
    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=client_id,
        title="Rule Delete Test Ticket",
        ticket_type="AR",
        current_status="OPEN",
        current_priority=TicketPriority.MEDIUM,
        custom_fields={},
    )
    session.add(ticket)
    await session.flush()
    return ticket


def _build_service(session) -> RuleService:
    return RuleService(
        RuleRepository(session),
        MailFolderRepository(session),
        DistributionListRepository(session),
        InteractionRepository(session),
    )


async def _create_folder_rule(service, *, folder_name: str, current_user: User):
    request = RuleCreate(
        name=f"Rule delete test {uuid.uuid4().hex[:8]}",
        category="mail_rule",
        is_enabled=True,
        conditions=RuleConditionGroup.model_validate(
            {
                "combinator": "AND",
                "rules": [
                    {
                        "field": "sender_domain",
                        "operator": "equals",
                        "value": "never-real-domain.example",
                    }
                ],
            }
        ),
        exceptions=RuleConditionGroup.model_validate({"combinator": "AND", "rules": []}),
        actions=[RuleActionItem.model_validate({"type": "create_folder", "folder_name": folder_name})],
        stop_processing=False,
        shared_user_ids=[],
    )
    return await service.create(request, current_user=current_user)


async def test_delete_rule_deletes_folder_and_unfiles_its_message(db_session):
    # Test 1 — basic case: the rule-owned folder is actually deleted,
    # and the message it held is preserved with folder_id cleared
    # (never deleted), so it becomes a normal Inbox item again.
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]
    client = await _make_client(db_session, account_manager_id=admin.user_id)

    service = _build_service(db_session)
    folder_name = f"Rule Delete Test Folder {uuid.uuid4().hex[:8]}"
    rule = await _create_folder_rule(service, folder_name=folder_name, current_user=admin)

    folder_repository = MailFolderRepository(db_session)
    folder = await folder_repository.get_by_name(folder_name)
    assert folder is not None
    assert folder.is_rule_created is True

    email = await _make_email(db_session, client_id=client.client_id, folder_id=folder.folder_id)

    await service.delete(rule.rule_id, current_user=admin)

    assert await RuleRepository(db_session).get_by_id(rule.rule_id) is None
    assert await folder_repository.get_by_name(folder_name) is None

    reloaded_email = await InteractionRepository(db_session).get_by_id(email.interaction_id)
    assert reloaded_email is not None
    assert reloaded_email.folder_id is None


async def test_delete_rule_unfiles_multiple_messages(db_session):
    # Test 2 — multiple emails in the folder all get unfiled, none lost.
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]
    client = await _make_client(db_session, account_manager_id=admin.user_id)

    service = _build_service(db_session)
    folder_name = f"Rule Delete Test Multi Folder {uuid.uuid4().hex[:8]}"
    rule = await _create_folder_rule(service, folder_name=folder_name, current_user=admin)

    folder_repository = MailFolderRepository(db_session)
    folder = await folder_repository.get_by_name(folder_name)
    assert folder is not None

    emails = [
        await _make_email(db_session, client_id=client.client_id, folder_id=folder.folder_id)
        for _ in range(3)
    ]

    await service.delete(rule.rule_id, current_user=admin)

    assert await folder_repository.get_by_name(folder_name) is None
    interaction_repository = InteractionRepository(db_session)
    for email in emails:
        reloaded = await interaction_repository.get_by_id(email.interaction_id)
        assert reloaded is not None
        assert reloaded.folder_id is None


async def test_delete_rule_preserves_ticket_relationship(db_session):
    # Test 3 — a ticketed interaction keeps its ticket_id; only
    # folder_id is cleared.
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]
    client = await _make_client(db_session, account_manager_id=admin.user_id)
    ticket = await _make_ticket(db_session, client_id=client.client_id)

    service = _build_service(db_session)
    folder_name = f"Rule Delete Test Ticketed Folder {uuid.uuid4().hex[:8]}"
    rule = await _create_folder_rule(service, folder_name=folder_name, current_user=admin)

    folder_repository = MailFolderRepository(db_session)
    folder = await folder_repository.get_by_name(folder_name)
    assert folder is not None

    email = await _make_email(
        db_session,
        client_id=client.client_id,
        folder_id=folder.folder_id,
        ticket_id=ticket.ticket_id,
    )

    await service.delete(rule.rule_id, current_user=admin)

    reloaded_email = await InteractionRepository(db_session).get_by_id(email.interaction_id)
    assert reloaded_email is not None
    assert reloaded_email.folder_id is None
    assert reloaded_email.ticket_id == ticket.ticket_id


async def test_delete_rule_still_removes_folder_with_no_messages(db_session):
    # Test 9 — an empty rule-owned folder is still deleted outright.
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]

    service = _build_service(db_session)
    folder_name = f"Rule Delete Test Empty Folder {uuid.uuid4().hex[:8]}"
    rule = await _create_folder_rule(service, folder_name=folder_name, current_user=admin)

    folder_repository = MailFolderRepository(db_session)
    assert await folder_repository.get_by_name(folder_name) is not None

    await service.delete(rule.rule_id, current_user=admin)

    assert await folder_repository.get_by_name(folder_name) is None


async def test_delete_rule_preserves_folder_still_referenced_by_another_rule(db_session):
    # Test 6 — two rules share the same folder name; deleting one must
    # never touch the folder the other still depends on.
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]

    service = _build_service(db_session)
    folder_name = f"Rule Delete Test Shared Folder {uuid.uuid4().hex[:8]}"
    rule_a = await _create_folder_rule(service, folder_name=folder_name, current_user=admin)
    rule_b = await _create_folder_rule(service, folder_name=folder_name, current_user=admin)

    folder_repository = MailFolderRepository(db_session)
    folder = await folder_repository.get_by_name(folder_name)
    assert folder is not None

    await service.delete(rule_a.rule_id, current_user=admin)

    assert await RuleRepository(db_session).get_by_id(rule_a.rule_id) is None
    assert await RuleRepository(db_session).get_by_id(rule_b.rule_id) is not None
    surviving_folder = await folder_repository.get_by_name(folder_name)
    assert surviving_folder is not None
    assert surviving_folder.folder_id == folder.folder_id


async def test_delete_rule_preserves_manually_created_folder_and_its_messages(db_session):
    # Test 7 — a folder created by hand (POST /folders, is_rule_created
    # False) that a rule's move_to_folder action merely references must
    # never be auto-deleted, and its existing messages/filing must be
    # left completely alone, even though this rule is its only
    # referencing rule.
    admin = await _get_super_admin(db_session)
    admin.permissions = ["rule:manage"]
    client = await _make_client(db_session, account_manager_id=admin.user_id)

    folder_repository = MailFolderRepository(db_session)
    manual_folder_name = f"Rule Delete Test Manual Folder {uuid.uuid4().hex[:8]}"
    manual_folder = await folder_repository.create(manual_folder_name, created_by=admin.user_id)
    assert manual_folder.is_rule_created is False

    email = await _make_email(
        db_session, client_id=client.client_id, folder_id=manual_folder.folder_id
    )

    service = _build_service(db_session)
    rule = await _create_folder_rule(service, folder_name=manual_folder_name, current_user=admin)

    await service.delete(rule.rule_id, current_user=admin)

    assert await RuleRepository(db_session).get_by_id(rule.rule_id) is None
    surviving_folder = await folder_repository.get_by_name(manual_folder_name)
    assert surviving_folder is not None
    assert surviving_folder.folder_id == manual_folder.folder_id

    reloaded_email = await InteractionRepository(db_session).get_by_id(email.interaction_id)
    assert reloaded_email is not None
    assert reloaded_email.folder_id == manual_folder.folder_id

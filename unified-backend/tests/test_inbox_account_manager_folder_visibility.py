# test_inbox_account_manager_folder_visibility.py
#
# DB-required regression coverage for: an Account Manager must never
# lose default-Inbox visibility into their own client's mail just
# because a Rule someone ELSE created also files that mail into a
# folder. InteractionRepository.list_inbox's/count_by_view's "pending"
# branch used to exclude ANY folder-filed item (Interaction.folder_id
# set) unconditionally, for every viewer — including the very Account
# Manager who owns the client, even when they had nothing to do with
# the rule that filed it away. Fixed by making that exclusion
# conditional, for an Account Manager only, on whether THEY are the
# creator of a rule currently filing into that folder — see
# InboxService._resolve_scope's account_manager_self_filed_folder_ids
# and list_inbox's/count_by_view's own docstrings. Same real-DB-
# inside-a-rolled-back-transaction convention as
# test_inbox_folder_exclusion.py / test_folder_sharing_visibility.py.

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import Role, User

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.enums import InteractionDirection, InteractionStatus
from app.ticketing.models.client import Client
from app.ticketing.models.interaction import Interaction
from app.ticketing.models.rule import Rule
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.services.inbox_service import InboxService
from app.ticketing.services.rule_access import folder_name_to_rules


@pytest.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


async def _get_account_manager(session) -> User:
    result = await session.execute(
        select(User)
        .options(joinedload(User.role))
        .join(Role, Role.role_id == User.role_id)
        .where(Role.name == "Account Manager", User.is_active.is_(True))
    )
    am = result.unique().scalars().first()
    if am is None:
        pytest.skip("No active seeded Account Manager found to use as client owner.")
    return am


async def _get_other_user(session, exclude_user_id) -> User:
    result = await session.execute(
        select(User).where(User.user_id != exclude_user_id, User.is_active.is_(True))
    )
    other = result.scalars().first()
    if other is None:
        pytest.skip("No other active seeded user found to use as an unrelated rule creator.")
    return other


async def _make_client(session, *, account_manager_id) -> Client:
    client = Client(
        client_id=uuid.uuid4(),
        name="AM Folder Visibility Test Client",
        inbox_email=f"am-folder-visibility-test-{uuid.uuid4().hex[:8]}@example.com",
        account_manager_id=account_manager_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()
    return client


async def _make_email(session, *, client_id, folder_id=None, subject="Test") -> Interaction:
    interaction = Interaction(
        interaction_id=uuid.uuid4(),
        interaction_type="EMAIL",
        direction=InteractionDirection.INBOUND,
        status=InteractionStatus.PENDING,
        payload={
            "subject": subject,
            "body": "Test body",
            "from_email": "client@example.com",
            "to_email": "support@probeps.com",
            "client_name": "AM Folder Visibility Test Client",
        },
        parent_interaction_id=None,
        ticket_id=None,
        client_id=client_id,
        folder_id=folder_id,
        is_visible=True,
        subject=subject,
        received_at=datetime.now(timezone.utc),
    )
    session.add(interaction)
    await session.flush()
    return interaction


async def _make_filing_rule(session, *, created_by, folder_name) -> Rule:
    rule = Rule(
        rule_id=uuid.uuid4(),
        name="Test AM folder visibility rule",
        category="MAIL_RULE",
        is_enabled=True,
        conditions={"combinator": "AND", "rules": []},
        exceptions={"combinator": "AND", "rules": []},
        actions=[{"type": "move_to_folder", "folder_name": folder_name}],
        priority=1,
        created_by=created_by,
    )
    session.add(rule)
    await session.flush()
    return rule


async def _self_filed_folder_ids(session, *, account_manager_id) -> list:
    """Mirrors InboxService._resolve_scope's own computation exactly."""

    rule_repository = RuleRepository(session)
    folder_repository = MailFolderRepository(session)
    all_rules = await rule_repository.list_all()
    name_to_rules = folder_name_to_rules(all_rules)
    all_folders = await folder_repository.list_all()
    return [
        folder.folder_id
        for folder in all_folders
        if any(
            rule.created_by == account_manager_id
            for rule in name_to_rules.get(folder.name, [])
        )
    ]


async def test_am_owned_folder_rule_still_excludes_from_pending(db_session):
    """
    If the Account Manager THEMSELVES created the rule that files
    mail into a folder, today's "moved out of Pending, still visible
    in All Mail/the folder" behavior is unchanged — they organized
    their own inbox, matching the requirement's own carve-out.
    """
    am = await _get_account_manager(db_session)
    client = await _make_client(db_session, account_manager_id=am.user_id)

    folder_repository = MailFolderRepository(db_session)
    folder = await folder_repository.create(
        f"AM Own Rule Folder {uuid.uuid4().hex[:8]}", created_by=am.user_id
    )
    await _make_filing_rule(db_session, created_by=am.user_id, folder_name=folder.name)

    filed_email = await _make_email(
        db_session, client_id=client.client_id, folder_id=folder.folder_id
    )

    self_filed_folder_ids = await _self_filed_folder_ids(
        db_session, account_manager_id=am.user_id
    )
    assert folder.folder_id in self_filed_folder_ids

    repo = InteractionRepository(db_session)

    pending_items, pending_total = await repo.list_inbox(
        account_manager_id=am.user_id,
        view="pending",
        account_manager_self_filed_folder_ids=self_filed_folder_ids,
    )
    assert filed_email.interaction_id not in {i.interaction_id for i in pending_items}

    all_items, _ = await repo.list_inbox(account_manager_id=am.user_id, view="all")
    assert filed_email.interaction_id in {i.interaction_id for i in all_items}

    folder_items, _ = await repo.list_inbox(
        account_manager_id=am.user_id, view="all", folder_id=folder.folder_id
    )
    assert filed_email.interaction_id in {i.interaction_id for i in folder_items}

    counts = await repo.count_by_view(
        account_manager_id=am.user_id,
        account_manager_self_filed_folder_ids=self_filed_folder_ids,
    )
    assert counts["pending"] == pending_total


async def test_someone_elses_rule_does_not_hide_mail_from_account_manager(db_session):
    """
    The reported bug: a Rule created by someone OTHER than the owning
    Account Manager files a client's mail into a folder (alongside
    forwarding it elsewhere) — the Account Manager must still see it
    in their own default Pending Inbox, not just via All Mail/the
    folder.
    """
    am = await _get_account_manager(db_session)
    other_user = await _get_other_user(db_session, am.user_id)
    client = await _make_client(db_session, account_manager_id=am.user_id)

    folder_repository = MailFolderRepository(db_session)
    folder = await folder_repository.create(
        f"Someone Elses Rule Folder {uuid.uuid4().hex[:8]}", created_by=other_user.user_id
    )
    await _make_filing_rule(
        db_session, created_by=other_user.user_id, folder_name=folder.name
    )

    filed_email = await _make_email(
        db_session, client_id=client.client_id, folder_id=folder.folder_id
    )
    unfiled_email = await _make_email(db_session, client_id=client.client_id, folder_id=None)

    self_filed_folder_ids = await _self_filed_folder_ids(
        db_session, account_manager_id=am.user_id
    )
    # The Account Manager authored no rule filing into this folder.
    assert folder.folder_id not in self_filed_folder_ids

    repo = InteractionRepository(db_session)

    pending_items, pending_total = await repo.list_inbox(
        account_manager_id=am.user_id,
        view="pending",
        account_manager_self_filed_folder_ids=self_filed_folder_ids,
    )
    pending_ids = {i.interaction_id for i in pending_items}
    assert filed_email.interaction_id in pending_ids
    assert unfiled_email.interaction_id in pending_ids

    all_items, _ = await repo.list_inbox(account_manager_id=am.user_id, view="all")
    assert filed_email.interaction_id in {i.interaction_id for i in all_items}

    folder_items, _ = await repo.list_inbox(
        account_manager_id=am.user_id, view="all", folder_id=folder.folder_id
    )
    assert filed_email.interaction_id in {i.interaction_id for i in folder_items}

    counts = await repo.count_by_view(
        account_manager_id=am.user_id,
        account_manager_self_filed_folder_ids=self_filed_folder_ids,
    )
    assert counts["pending"] == pending_total


async def test_resolve_scope_computes_self_filed_folder_ids_end_to_end(db_session):
    """
    Service-level check: InboxService.get_inbox (via _resolve_scope's
    own lazy RuleRepository/MailFolderRepository/folder_name_to_rules
    computation) produces the same restored visibility the two tests
    above assume at the repository layer — not just the raw query.
    """
    am = await _get_account_manager(db_session)
    other_user = await _get_other_user(db_session, am.user_id)
    client = await _make_client(db_session, account_manager_id=am.user_id)
    am.permissions = ["communication:view_assigned"]

    folder_repository = MailFolderRepository(db_session)
    folder = await folder_repository.create(
        f"Service Level Folder {uuid.uuid4().hex[:8]}", created_by=other_user.user_id
    )
    await _make_filing_rule(
        db_session, created_by=other_user.user_id, folder_name=folder.name
    )

    filed_email = await _make_email(
        db_session, client_id=client.client_id, folder_id=folder.folder_id
    )

    inbox_service = InboxService(InteractionRepository(db_session))

    result = await inbox_service.get_inbox(am, view="pending")
    assert filed_email.interaction_id in {item.interaction_id for item in result.items}
